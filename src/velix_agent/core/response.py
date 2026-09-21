"""Agent Response representations for the Agent Core."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ResponseStatus = Literal["success", "error"]


@dataclass(frozen=True)
class AgentResponse:
    """A strongly typed representation of an agent's response."""

    text: str
    status: ResponseStatus = "success"
    metadata: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in ("success", "error"):
            raise ValueError(f"Invalid status: {self.status}")
        if self.status == "error" and not self.error:
            raise ValueError("Error response must include error details.")
