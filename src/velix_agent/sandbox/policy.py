from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SupportStatus = Literal["SUPPORTED", "UNSUPPORTED", "NOT_AVAILABLE"]

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

@dataclass
class SandboxPolicy:
    workspace_root: Path
    allow_network: bool = False
    max_execution_time: int = 30
    max_output_size: int = 50_000
    cpu_limit: bool = True
    memory_limit: int | None = None
    process_limit: int | None = None
    secret_filtering: bool = True
    secrets: list[str] = field(default_factory=list)
