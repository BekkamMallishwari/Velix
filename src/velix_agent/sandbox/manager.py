import platform
from pathlib import Path

from velix_agent.sandbox.backends.base import SandboxBackend
from velix_agent.sandbox.policy import SandboxPolicy
from velix_agent.sandbox.result import SandboxError, SandboxResult


class SandboxManager:
    backend: SandboxBackend | None

    def __init__(self, backend: SandboxBackend | None = None, _force_none: bool = False):
        if _force_none:
            self.backend = None
        elif backend is None:
            if platform.system() == "Darwin":
                from velix_agent.sandbox.backends.macos import MacOSSandboxBackend

                self.backend = MacOSSandboxBackend()
            else:
                self.backend = None
        else:
            self.backend = backend

    def execute(self, command: list[str], workspace_root: str | Path, timeout: int = 30) -> SandboxResult:
        if self.backend is None:
            raise SandboxError(f"Sandbox backend unavailable for platform: {platform.system()}")

        root = Path(workspace_root).resolve()
        if not root.is_dir():
            raise SandboxError(f"Invalid workspace root: {root}")

        policy = SandboxPolicy(workspace_root=root, allow_network=False)
        return self.backend.execute(command, policy, timeout=timeout)
