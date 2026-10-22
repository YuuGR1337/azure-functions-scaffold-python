from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal

from tools.verification_evidence import redact
from tools.verification_manifest import REQUIRED_DIAGNOSTICS
from tools.verification_process import run

Category = Literal["PASS", "ADVISORY", "REQUIRED_FINDING", "CLI_ERROR", "CRASH"]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    category: Category
    exit_code: int


def classify(document: str, code: int) -> Diagnostic:
    if code == 2:
        return Diagnostic("CLI_ERROR", code)
    if code not in (0, 1):
        return Diagnostic("CRASH", code)
    try:
        payload = json.loads(document)
        results = payload["results"]
        if not isinstance(results, list) or not results:
            raise ValueError("Missing diagnostics results")
        findings = [item for result in results for item in result["items"]]
        if not findings:
            raise ValueError("Missing diagnostic findings")
        for item in findings:
            if item["status"] not in {"pass", "warn", "fail", "skip"}:
                raise ValueError("Invalid finding status")
            if item["severity"] not in {"error", "warning", "info"}:
                raise ValueError("Invalid finding severity")
            if not isinstance(item["rule_id"], str):
                raise ValueError("Missing rule identity")
        blocking = any(
            item["rule_id"] in REQUIRED_DIAGNOSTICS and item["status"] in {"fail", "skip"}
            for item in findings
        )
        advisory = any(item["status"] in {"fail", "warn"} for item in findings)
    except (ValueError, KeyError, TypeError):
        return Diagnostic("CRASH", code or 1)
    if blocking:
        return Diagnostic("REQUIRED_FINDING", 1)
    return Diagnostic("ADVISORY" if advisory or code else "PASS", 0)


def diagnose(project: Path, python: Path, directory: Path) -> Diagnostic:
    directory.mkdir(parents=True, exist_ok=True)
    code = run(
        [
            str(python.parent / "azure-functions-doctor"),
            "doctor",
            "--path",
            str(project),
            "--format",
            "json",
            "--output",
            str(directory / "doctor.json"),
        ],
        directory / "doctor.stderr.log",
        timeout=120,
        cwd=project,
    )
    output = directory / "doctor.json"
    document = redact(output.read_text()) if output.exists() else ""
    if output.exists():
        output.write_text(document)
    return classify(document, code)
