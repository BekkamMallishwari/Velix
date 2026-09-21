"""Base provider interface for VelixAgent Model Provider Layer."""

import abc

from velix_agent.core.message import Message
from velix_agent.core.response import AgentResponse


class Provider(abc.ABC):
    """Abstract base class for all Model Providers."""

    @abc.abstractmethod
    def generate(self, messages: list[Message]) -> AgentResponse:
        """Generate a response based on the conversation history."""
        pass
