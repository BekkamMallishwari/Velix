"""Message representations for the Agent Core."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Literal

MessageRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class MessagePart:
    """Base class for parts of a multimodal message."""

    pass


@dataclass(frozen=True)
class TextPart(MessagePart):
    """A text part of a multimodal message."""

    text: str


@dataclass(frozen=True)
class ImagePart(MessagePart):
    """An image part of a multimodal message (prepared for Phase 4)."""

    mime_type: str
    data: bytes


@dataclass(frozen=True)
class DocumentPart(MessagePart):
    """A document/file part (PDF, code, text) of a multimodal message."""

    mime_type: str
    data: bytes


@dataclass(frozen=True)
class ErrorPart(MessagePart):
    """Represents a failure to fetch or parse a part (e.g., dead URL)."""

    error: str


@dataclass
class Message:
    """A strongly typed representation of a conversation message.

    Supports multimodal parts.
    """

    role: MessageRole
    content: list[MessagePart]
    timestamp: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )

    def __init__(
        self,
        role: MessageRole,
        content: str | list[MessagePart],
        timestamp: datetime.datetime | None = None,
    ) -> None:
        if role not in ("system", "user", "assistant"):
            raise ValueError(f"Invalid role: {role}")
        if not content:
            raise ValueError("Message content cannot be empty.")

        object.__setattr__(self, "role", role)

        if isinstance(content, str):
            object.__setattr__(self, "content", [TextPart(text=content)])
        else:
            object.__setattr__(self, "content", content)

        object.__setattr__(
            self,
            "timestamp",
            timestamp if timestamp is not None else datetime.datetime.now(datetime.UTC),
        )
