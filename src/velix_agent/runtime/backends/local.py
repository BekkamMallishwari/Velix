from pathlib import Path

from velix_agent.runtime.backends.base import RuntimeBackend
from velix_agent.runtime.detector import RuntimeDetector
from velix_agent.runtime.models import RuntimeCapability, RuntimeInfo, RuntimeStatus
from velix_agent.sandbox.manager import SandboxManager


class LocalRuntimeBackend(RuntimeBackend):
    def __init__(self, sandbox_manager: SandboxManager | None = None):
        self.detector = RuntimeDetector(sandbox_manager)

    @classmethod
    def get_capabilities(cls) -> dict[str, RuntimeCapability]:
        return {
            "Python": RuntimeCapability(detection="SUPPORTED"),
            "Node.js": RuntimeCapability(detection="SUPPORTED"),
            "Java": RuntimeCapability(detection="SUPPORTED"),
            "Go": RuntimeCapability(detection="SUPPORTED"),
            "Rust": RuntimeCapability(detection="SUPPORTED"),
        }

    def detect_all(self, workspace_root: Path) -> dict[str, RuntimeInfo]:
        return {
            "Python": self.detector.detect_python(workspace_root),
            "Node.js": self.detector.detect_node(workspace_root),
            "Java": self.detector.detect_java(workspace_root),
            "Go": self.detector.detect_go(workspace_root),
            "Rust": self.detector.detect_rust(workspace_root),
        }

    def get_runtime(self, name: str, workspace_root: Path) -> RuntimeInfo:
        n = name.lower()
        if n == "python":
            return self.detector.detect_python(workspace_root)
        elif n in ("node", "node.js"):
            return self.detector.detect_node(workspace_root)
        elif n == "java":
            return self.detector.detect_java(workspace_root)
        elif n == "go":
            return self.detector.detect_go(workspace_root)
        elif n == "rust":
            return self.detector.detect_rust(workspace_root)
        return RuntimeInfo(name=name, status=RuntimeStatus.UNSUPPORTED)
