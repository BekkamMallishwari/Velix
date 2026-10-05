import platform
from pathlib import Path
from typing import TYPE_CHECKING

from velix_agent.sandbox.backends.base import SandboxBackend
from velix_agent.sandbox.policy import SandboxPolicy

if TYPE_CHECKING:
    from velix_agent.sandbox.policy import SandboxCapabilities
from velix_agent.sandbox.result import SandboxError, SandboxResult


class SandboxManager:
    backend: SandboxBackend | None

    def __init__(self, backend: SandboxBackend | None = None, _force_none: bool = False):
        if _force_none:
            self.backend = None
        elif backend is None:
            sys_name = platform.system()
            if sys_name == "Darwin":
                from velix_agent.sandbox.backends.macos import MacOSSandboxBackend
                self.backend = MacOSSandboxBackend()
            elif sys_name == "Linux":
                from velix_agent.sandbox.backends.linux import LinuxSandboxBackend
                self.backend = LinuxSandboxBackend()
            elif sys_name == "Windows":
                from velix_agent.sandbox.backends.windows import WindowsSandboxBackend
                self.backend = WindowsSandboxBackend()
            else:
                self.backend = None
        else:
            self.backend = backend

    def get_capabilities(self) -> "SandboxCapabilities":
        from velix_agent.sandbox.policy import SandboxCapabilities
        if self.backend is None:
            return SandboxCapabilities(
                filesystem_isolation="NOT_AVAILABLE",
                network_isolation="NOT_AVAILABLE",
                cpu_limit="NOT_AVAILABLE",
                memory_limit="NOT_AVAILABLE",
                process_limit="NOT_AVAILABLE",
                timeout="NOT_AVAILABLE",
                output_limit="NOT_AVAILABLE",
                secret_filtering="NOT_AVAILABLE",
            )
        return self.backend.get_capabilities()

    def execute(
        self,
        command: list[str],
        workspace_root: str | Path,
        timeout: int = 30,
        allow_network: bool = False,
    ) -> SandboxResult:
        if self.backend is None:
            raise SandboxError(f"Sandbox backend unavailable for platform: {platform.system()}")

        caps = self.get_capabilities()
        if not allow_network and caps.network_isolation == "UNSUPPORTED":
            raise SandboxError("Network isolation is unsupported by the active backend.")

        root = Path(workspace_root).resolve()
        if not root.is_dir():
            raise SandboxError(f"Invalid workspace root: {root}")

        policy = SandboxPolicy(workspace_root=root, allow_network=allow_network)
        return self.backend.execute(command, policy, timeout=timeout)
