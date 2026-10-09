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
    workspace_root: Path
    mode: SandboxPolicyMode = SandboxPolicyMode.STRICT
    allow_network: bool = False
    max_execution_time: int = 30
    max_output_size: int = 50_000
    cpu_limit: bool = True
    memory_limit: int | None = None
    process_limit: int | None = None
    secret_filtering: bool = True
    secrets: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
