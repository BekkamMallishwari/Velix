from pathlib import Path

from velix_agent.runtime.backends.base import RuntimeBackend
from velix_agent.runtime.backends.local import LocalRuntimeBackend
from velix_agent.runtime.models import RuntimeCapability, RuntimeInfo
from velix_agent.sandbox.manager import SandboxManager


class RuntimeManager:
    def __init__(
        self,
        backend: RuntimeBackend | None = None,
        sandbox_manager: SandboxManager | None = None,
    ):
        self.backend: RuntimeBackend
        if backend is None:
            self.backend = LocalRuntimeBackend(sandbox_manager)
        else:
            self.backend = backend

    def get_capabilities(self) -> dict[str, RuntimeCapability]:
        return self.backend.get_capabilities()

    def detect_all(self, workspace_root: Path | str) -> dict[str, RuntimeInfo]:
        root = Path(workspace_root).resolve()
        return self.backend.detect_all(root)

    def get_runtime(self, name: str, workspace_root: Path | str) -> RuntimeInfo:
        root = Path(workspace_root).resolve()
        return self.backend.get_runtime(name, root)
