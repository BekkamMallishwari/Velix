from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

SupportStatus = Literal[
    "SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "NOT_AVAILABLE", "NOT_APPLICABLE"
]


@dataclass
class SandboxCapabilities:
    filesystem_isolation: SupportStatus
    network_isolation: SupportStatus
    cpu_limit: SupportStatus
    memory_limit: SupportStatus
    process_limit: SupportStatus
    timeout: SupportStatus
    output_limit: SupportStatus
    secret_filtering: SupportStatus
    disk_limit: SupportStatus
    runtime_isolation: SupportStatus
    observability: SupportStatus
    security_hardening: SupportStatus


class SandboxPolicyMode(Enum):
    STRICT = "STRICT"
    BALANCED = "BALANCED"
    DEVELOPMENT = "DEVELOPMENT"


@dataclass
class SandboxPolicy:
    """Security and execution policy for sandboxed command execution.

    Output Limit Contract:
        `max_output_size` sets the maximum number of raw bytes captured from each of
        stdout and stderr. If a stream emits more than `max_output_size` bytes, stream
        capture stops at that byte limit, `truncation_status` is marked True for that stream,
        and `OUTPUT_TRUNCATION_MARKER` is appended to the decoded output string.
    """
    workspace_root: Path
    mode: SandboxPolicyMode = SandboxPolicyMode.STRICT
    allow_network: bool = False
    max_execution_time: int = 30
    max_output_size: int = 50_000
    cpu_limit: bool = False
    memory_limit: int | None = None
    process_limit: int | None = None
    secret_filtering: bool = True
    secrets: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_output_size < 0:
            raise ValueError(
                f"max_output_size must be non-negative, got {self.max_output_size}"
            )
