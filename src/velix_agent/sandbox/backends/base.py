import abc

from velix_agent.sandbox.policy import SandboxCapabilities, SandboxPolicy
from velix_agent.sandbox.result import SandboxResult


class SandboxBackend(abc.ABC):
    @classmethod
    @abc.abstractmethod
    def get_capabilities(cls) -> SandboxCapabilities:
        pass

    @abc.abstractmethod
    def execute(
        self, command: list[str], policy: SandboxPolicy, timeout: int = 30
    ) -> SandboxResult:
        pass
