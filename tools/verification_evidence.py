from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import re
import subprocess
from typing import Literal
import xml.etree.ElementTree as ET

Status = Literal["PASS", "FAIL", "INCOMPLETE", "NOT_APPLICABLE"]


def read_xml_root(path: Path) -> ET.Element:
    """Parse a locally generated report, refusing entity declarations."""
    data = path.read_bytes()
    if b"<!ENTITY" in data.upper():
        raise ValueError("XML reports must not declare entities")
    return ET.fromstring(data)


@dataclass(frozen=True, slots=True)
class Summary:
    schema_version: int
    lane: str
    command: tuple[str, ...]
    selected: int
    passed: int
    failed: int
    skipped: int
    status: Status
    exit_code: int
    required: bool = True
    scope: str = "PARTIAL"
    reason: str = ""
    supporting_files: tuple[str, ...] = ()
    candidate_version: str = ""
    artifact_sha256: str = ""
    generated_python: str = ""
    sdk_version: str = ""
    generated_digest: str = ""
    deployed_artifact_identity: Status = "NOT_APPLICABLE"


def redact(text: str) -> str:
    text = re.sub(r"(?im)(authorization[\"']?\s*[:=]\s*)[^\r\n<\"]+", r"\1[REDACTED]", text)
    text = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"(?i)(DefaultEndpointsProtocol=)[^\s<\"']+", r"\1[REDACTED]", text)
    text = re.sub(
        r"(?i)(?<![\w-])((?:[\w-]*(?:token|password|secret|connection[_-]?string)|AccountKey|"
        r"SharedAccessSignature|AzureWebJobsStorage|x-functions-key|code|sig|sas|api[_-]?key)"
        r"[\"']?\s*[:=]\s*[\"']?)[^\s;&<\"']+",
        r"\1[REDACTED]",
        text,
    )
    for key, value in os.environ.items():
        if len(value) >= 6 and re.search(r"(?i)secret|token|password|connection|key|sas", key):
            text = text.replace(value, "[REDACTED]")
    return text


def environment() -> dict[str, str]:
    metadata = {"python": platform.python_version(), "platform": platform.platform()}
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    metadata["source_commit"] = result.stdout.strip()
    for package in ("azure-functions-scaffold", "azure-functions", "azure-functions-doctor"):
        try:
            metadata[package] = version(package)
        except PackageNotFoundError:
            metadata[package] = "not installed"
    return metadata


def collect(directory: Path, command: list[str], exit_code: int) -> Summary:
    cases: list[ET.Element] = []
    for path in directory.rglob("*junit*.xml"):
        root = read_xml_root(path)
        suites = list(root.iter("testsuite"))
        if not suites:
            raise ValueError("JUnit contains no testsuite")
        for suite in suites:
            actual_cases = list(suite.iter("testcase"))
            for counter, outcome in (
                ("tests", None),
                ("failures", "failure"),
                ("errors", "error"),
                ("skipped", "skipped"),
            ):
                actual = (
                    len(actual_cases)
                    if outcome is None
                    else sum(case.find(outcome) is not None for case in actual_cases)
                )
                if counter in suite.attrib and int(suite.attrib[counter]) != actual:
                    raise ValueError(f"JUnit counter mismatch: {counter}")
        cases.extend(root.iter("testcase"))
    failed = sum(c.find("failure") is not None or c.find("error") is not None for c in cases)
    skipped = sum(c.find("skipped") is not None for c in cases)
    passed = len(cases) - failed - skipped
    unexpected_skips = skipped
    if directory.name == "test":
        unexpected_skips -= sum(
            (skip := case.find("skipped")) is not None
            and skip.get("message", "").startswith("intentional historical content: ")
            and "test_docs_cli_examples" in case.get("classname", "")
            for case in cases
        )
    status: Status = "PASS"
    if exit_code or failed:
        status = "FAIL"
    elif not passed or unexpected_skips:
        status = "INCOMPLETE"
    return Summary(
        1,
        directory.name,
        tuple(command),
        len(cases),
        passed,
        failed,
        skipped,
        status,
        exit_code or int(status != "PASS"),
        reason="Required positive execution with no unexpected skips" if status != "PASS" else "",
    )


def publish(summary: Summary) -> None:
    text = redact(
        f"{summary.lane}: {summary.status} | scope={summary.scope} selected={summary.selected} "
        f"passed={summary.passed} failed={summary.failed} skipped={summary.skipped} "
        f"exit={summary.exit_code} | {summary.reason}"
    )
    print(text)
    if destination := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write("\n- " + text + "\n")


def save(directory: Path, summary: Summary) -> Summary:
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.rglob("*"):
        if path.is_file():
            path.write_text(
                redact(path.read_text(encoding="utf-8", errors="replace")), encoding="utf-8"
            )
    (directory / "environment.json").write_text(redact(json.dumps(environment(), indent=2)) + "\n")
    summary = replace(
        summary,
        command=tuple(redact(p) for p in summary.command),
        reason=redact(summary.reason),
        supporting_files=tuple(
            str(p) for p in sorted(directory.rglob("*")) if p.is_file() and p.name != "summary.json"
        ),
    )
    serialized = redact(json.dumps(asdict(summary), indent=2))
    (directory / "summary.json").write_text(serialized + "\n")
    return Summary(**json.loads(serialized))


def report(root: Path) -> int:
    paths = sorted(root.rglob("summary.json"))
    for path in paths:
        publish(Summary(**json.loads(path.read_text())))
    if not paths:
        print("No saved verification results")
    return int(not paths)
