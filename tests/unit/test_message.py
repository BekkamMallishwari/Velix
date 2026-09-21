"""Unit tests for the Message model."""

import pytest

from velix_agent.core.message import Message


def test_valid_message() -> None:
    """Test creating a valid message."""
    msg = Message(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content[0].text == "Hello"
    assert msg.timestamp is not None


def test_invalid_role() -> None:
    """Test creating a message with an invalid role."""
    with pytest.raises(ValueError, match="Invalid role"):
        Message(role="invalid", content="Hello")  # type: ignore


def test_empty_content() -> None:
    """Test creating a message with empty content."""
    with pytest.raises(ValueError, match=r"Message content cannot be empty."):
        Message(role="user", content="")
