"""Unit tests for the Session."""

from velix_agent.core.session import Session


def test_session_creation() -> None:
    """Test creating a session."""
    session = Session.create(system_message="System prompt")
    assert session.session_id is not None
    assert len(session.session_id) == 8
    assert session.created_at is not None
    assert len(session.context.get_messages()) == 1


def test_session_reset() -> None:
    """Test resetting a session."""
    session = Session.create()
    old_id = session.session_id
    session.context.add_user_message("Hello")

    session.reset(system_message="New prompt")
    assert session.session_id != old_id
    assert len(session.context.get_messages()) == 1
    assert session.context.get_messages()[0].role == "system"


def test_clear_conversation() -> None:
    """Test clearing the conversation but keeping the session ID."""
    session = Session.create()
    old_id = session.session_id
    session.context.add_user_message("Hello")

    session.clear_conversation()
    assert session.session_id == old_id
    assert len(session.context.get_messages()) == 0
