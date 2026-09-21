"""Conversation context for the Agent Core."""

from __future__ import annotations

from velix_agent.core.message import Message, MessagePart


class ConversationContext:
    """Maintains short-term conversation context.

    Stores the sequence of messages in the current session.
    """

    def __init__(self, system_message: str | None = None) -> None:
        self._messages: list[Message] = []
        if system_message:
            self._messages.append(Message(role="system", content=system_message))

    def add_message(self, message: Message) -> None:
        """Add a raw Message to the context."""
        self._messages.append(message)

    def add_user_message(self, content: str | list[MessagePart]) -> None:
        """Add a user message to the context."""
        self.add_message(Message(role="user", content=content))

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message to the context."""
        self.add_message(Message(role="assistant", content=content))

    def get_messages(self) -> list[Message]:
        """Retrieve all messages in the context."""
        return list(self._messages)

    def clear(self, system_message: str | None = None) -> None:
        """Clear the context, optionally re-adding a system message."""
        self._messages.clear()
        if system_message:
            self._messages.append(Message(role="system", content=system_message))
