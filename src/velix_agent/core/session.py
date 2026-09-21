"""Session management for the Agent Core."""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field

from velix_agent.core.context import ConversationContext


@dataclass
class Session:
    """Represents a single interactive VelixAgent conversation session."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )
    context: ConversationContext = field(default_factory=ConversationContext)

    @classmethod
    def create(cls, system_message: str | None = None) -> Session:
        """Create a new session, optionally with a system message."""
        context = ConversationContext(system_message=system_message)
        return cls(context=context)

    def reset(self, system_message: str | None = None) -> None:
        """Reset the session with a new ID and clear context."""
        self.session_id = str(uuid.uuid4())[:8]
        self.created_at = datetime.datetime.now(datetime.UTC)
        self.context.clear(system_message=system_message)

    def clear_conversation(self, system_message: str | None = None) -> None:
        """Clear the conversation context but keep the session ID."""
        self.context.clear(system_message=system_message)
