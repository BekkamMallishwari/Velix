import abc

from velix_agent.sandbox.policy import SandboxPolicy
from velix_agent.sandbox.result import SandboxResult


class SandboxBackend(abc.ABC):
    @abc.abstractmethod
    def execute(self, command: list[str], policy: SandboxPolicy, timeout: int = 30) -> SandboxResult:
        pass
