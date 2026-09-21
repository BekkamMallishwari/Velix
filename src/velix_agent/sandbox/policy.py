from dataclasses import dataclass
from pathlib import Path


@dataclass
class SandboxPolicy:
    workspace_root: Path
    allow_network: bool = False
