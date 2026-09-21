"""Unit tests for the ConversationContext."""

from velix_agent.core.context import ConversationContext


def test_context_initialization() -> None:
    """Test initializing context with and without a system message."""
    ctx = ConversationContext()
    assert len(ctx.get_messages()) == 0

    ctx_sys = ConversationContext(system_message="You are a helpful assistant.")
    messages = ctx_sys.get_messages()
    assert len(messages) == 1
    assert messages[0].role == "system"
    assert messages[0].content[0].text == "You are a helpful assistant."


def test_add_messages() -> None:
    """Test adding messages to the context."""
    ctx = ConversationContext()
    ctx.add_user_message("Hello")
    ctx.add_assistant_message("Hi there")

    messages = ctx.get_messages()
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content[0].text == "Hello"
    assert messages[1].role == "assistant"
    assert messages[1].content[0].text == "Hi there"


def test_clear_context() -> None:
    """Test clearing the context."""
    ctx = ConversationContext(system_message="System init")
    ctx.add_user_message("Hello")
    assert len(ctx.get_messages()) == 2

    ctx.clear()
    assert len(ctx.get_messages()) == 0

    ctx.clear(system_message="New system init")
    messages = ctx.get_messages()
    assert len(messages) == 1
    assert messages[0].role == "system"
    assert messages[0].content[0].text == "New system init"
