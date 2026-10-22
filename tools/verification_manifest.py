from __future__ import annotations

from typing import Final

TEMPLATES: Final = (
    "http",
    "timer",
    "queue",
    "blob",
    "servicebus",
    "eventhub",
    "cosmosdb",
    "durable",
    "ai",
    "langgraph",
)
FAMILIES: Final = {
    "test": "offline generator unit and generated-artifact structure; coverage >=95%",
    "generated-project": "all ten strict templates: compile, lint, typecheck, pytest, diagnostics",
    "wheel-smoke": "candidate wheel installed outside checkout; installed CLI generates projects",
    "host-smoke": "generated HTTP app indexed and invoked through owned func and Azurite",
    "azure-generation": "existing generated project structure and syntax",
    "azure-remote": "existing deployed HTTPS endpoint health payload",
}
NO_TEST_TEMPLATES: Final[dict[str, str]] = {}
REQUIRED_DIAGNOSTICS: Final = frozenset(
    {
        "check_python_version",
        "check_requirements_txt",
        "check_azure_functions_library",
        "check_host_json",
        "check_host_json_version",
    }
)
