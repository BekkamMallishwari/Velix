"""Base provider interface for VelixAgent Model Provider Layer."""

import abc
from typing import TYPE_CHECKING

from velix_agent.core.message import Message
from velix_agent.core.response import AgentResponse

if TYPE_CHECKING:
    from velix_agent.tools.base import Tool


class Provider(abc.ABC):
    """Abstract base class for all Model Providers."""

    @abc.abstractmethod
    def generate(
        self, messages: list[Message], tools: list["Tool"] | None = None
    ) -> AgentResponse:
        """Generate a response based on the conversation history."""
        pass
