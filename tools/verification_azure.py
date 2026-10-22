from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import version
import ipaddress
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from tools.verification_evidence import Summary, collect, publish, save
from tools.verification_process import run


def preflight(environment: Mapping[str, str]) -> str:
    required = ("E2E_SCAFFOLDED_DIR", "E2E_BASE_URL", "E2E_EXPECTED_VERSION", "VERIFICATION_WHEEL")
    missing = [key for key in required if not environment.get(key, "").strip()]
    if missing:
        return "Missing prerequisites: " + ", ".join(missing)
    project = Path(environment["E2E_SCAFFOLDED_DIR"])
    if not all(
        (project / name).is_file() for name in ("function_app.py", "host.json", "pyproject.toml")
    ):
        return "E2E_SCAFFOLDED_DIR must identify the generated deployment input"
    try:
        url = urlsplit(environment["E2E_BASE_URL"])
        hostname = url.hostname or ""
        port = url.port
    except ValueError:
        return "E2E_BASE_URL is malformed"
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        return "E2E_BASE_URL must identify an existing deployed HTTPS endpoint without credentials"
    if hostname == "localhost" or hostname.endswith(".localhost") or port == 0:
        return "E2E_BASE_URL must not identify a local host"
    try:
        if not ipaddress.ip_address(hostname).is_global:
            return "E2E_BASE_URL must identify a public deployed host"
    except ValueError:
        if "." not in hostname:
            return "E2E_BASE_URL requires a deployed hostname"
    if environment["E2E_EXPECTED_VERSION"] != version("azure-functions-scaffold"):
        return "E2E_EXPECTED_VERSION differs from installed candidate"
    if not Path(environment["VERIFICATION_WHEEL"]).is_file():
        return "VERIFICATION_WHEEL candidate is missing"
    return ""


def azure(directory: Path) -> list[Summary]:
    reason = preflight(os.environ)
    if reason:
        return [
            Summary(
                1, "azure-e2e", ("make", "e2e-azure"), 0, 0, 0, 0, "INCOMPLETE", 2, reason=reason
            )
        ]
    outcomes = []
    for phase, expression in (
        ("azure-generation", "scaffolded"),
        ("azure-remote", "not scaffolded"),
    ):
        destination = directory / phase
        command = [
            sys.executable,
            "-m",
            "pytest",
            "tests/e2e",
            "-o",
            "addopts=",
            "-m",
            "e2e",
            "-k",
            expression,
            "--junitxml=" + str(destination / "junit.xml"),
        ]
        code = run(command, destination / "logs/pytest.log", 900)
        summary = replace(
            collect(destination, command, code),
            scope="AZURE",
            candidate_version=os.environ["E2E_EXPECTED_VERSION"],
            artifact_sha256=sha256(Path(os.environ["VERIFICATION_WHEEL"]).read_bytes()).hexdigest(),
            deployed_artifact_identity="INCOMPLETE",
            reason="Deployment provenance is workflow-owned; no remote version endpoint",
        )
        publish(save(destination, summary))
        outcomes.append(summary)
    return outcomes
