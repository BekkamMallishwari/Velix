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

    def add_assistant_message(self, content: str | list[MessagePart]) -> None:
        """Add an assistant message to the context.

        Accepts either a plain string or a pre-built list of MessageParts so
        that multipart assistant messages (e.g. TextPart + ToolCallPart) are
        preserved exactly without any re-wrapping.
        """
        self.add_message(Message(role="assistant", content=content))

    def add_tool_result_message(self, parts: list[MessagePart]) -> None:
        """Add a user message containing one or more ToolResultPart(s).

        This is a dedicated helper for feeding tool results back into the
        conversation.  It follows the same Message/MessagePart design as
        add_user_message and does not introduce any new abstraction.
        """
        self.add_message(Message(role="user", content=parts))

    def get_messages(self) -> list[Message]:
        """Retrieve all messages in the context."""
        return list(self._messages)

    def clear(self, system_message: str | None = None) -> None:
        """Clear the context, optionally re-adding a system message."""
        self._messages.clear()
        if system_message:
            self._messages.append(Message(role="system", content=system_message))
