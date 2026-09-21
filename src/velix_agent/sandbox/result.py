from dataclasses import dataclass


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    command: list[str]


class SandboxError(Exception):
    """Exception raised when the sandbox fails to initialize or execute."""

    pass
