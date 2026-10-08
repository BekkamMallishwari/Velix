from dataclasses import dataclass, field
from typing import Any


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    command: list[str]
    execution_id: str = ""
    backend: str = ""
    duration: float = 0.0
    resource_usage: dict[str, Any] = field(default_factory=dict)
    security_events: list[str] = field(default_factory=list)
    truncation_status: dict[str, bool] = field(default_factory=dict)


class SandboxError(Exception):
    """Exception raised when the sandbox fails to initialize or execute."""

    pass
