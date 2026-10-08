from abc import ABC, abstractmethod
from pathlib import Path

from velix_agent.runtime.models import RuntimeCapability, RuntimeInfo


class RuntimeBackend(ABC):
    @classmethod
    @abstractmethod
    def get_capabilities(cls) -> dict[str, RuntimeCapability]:
        pass

    @abstractmethod
    def detect_all(self, workspace_root: Path) -> dict[str, RuntimeInfo]:
        pass

    @abstractmethod
    def get_runtime(self, name: str, workspace_root: Path) -> RuntimeInfo:
        pass
