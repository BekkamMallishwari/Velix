"""Base abstractions for the Tool Layer."""

import abc
from dataclasses import dataclass, field
from typing import Any, Literal

ToolStatus = Literal["success", "error"]


@dataclass(frozen=True)
class ToolResult:
    """A strongly typed representation of a tool's result."""

    status: ToolStatus
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in ("success", "error"):
            raise ValueError(f"Invalid status: {self.status}")
        if self.status == "error" and not self.error:
            raise ValueError("Error response must include error details.")


class Tool(abc.ABC):
    """Abstract base class for all tools."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """The stable name of the tool."""
        pass

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """A clear description of what the tool does."""
        pass

    @abc.abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments."""
        pass
