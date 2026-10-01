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


# ---------------------------------------------------------------------------
# P0 context API improvements
# ---------------------------------------------------------------------------


def test_add_assistant_message_with_string() -> None:
    """add_assistant_message with a plain string wraps it in a TextPart."""
    from velix_agent.core.message import TextPart

    ctx = ConversationContext()
    ctx.add_assistant_message("Hello from assistant")

    messages = ctx.get_messages()
    assert len(messages) == 1
    msg = messages[0]
    assert msg.role == "assistant"
    assert len(msg.content) == 1
    assert isinstance(msg.content[0], TextPart)
    assert msg.content[0].text == "Hello from assistant"


def test_add_assistant_message_with_multipart() -> None:
    """add_assistant_message with a list[MessagePart] preserves parts verbatim."""
    from velix_agent.core.message import TextPart, ToolCallPart

    tc = ToolCallPart(tool_name="read_file", args={"path": "/tmp/a.txt"}, id="tc-001")
    parts = [TextPart(text="Let me read that file."), tc]

    ctx = ConversationContext()
    ctx.add_assistant_message(parts)

    messages = ctx.get_messages()
    assert len(messages) == 1
    msg = messages[0]
    assert msg.role == "assistant"
    assert len(msg.content) == 2
    assert isinstance(msg.content[0], TextPart)
    assert msg.content[0].text == "Let me read that file."
    assert isinstance(msg.content[1], ToolCallPart)


def test_add_assistant_message_preserves_tool_call_part_fields() -> None:
    """ToolCallPart.id and .args are preserved exactly when stored via add_assistant_message."""
    from velix_agent.core.message import ToolCallPart

    tc = ToolCallPart(
        tool_name="run_command",
        args={"cmd": "ls -la", "cwd": "/home"},
        id="unique-id-42",
    )

    ctx = ConversationContext()
    ctx.add_assistant_message([tc])

    stored = ctx.get_messages()[0].content[0]
    assert isinstance(stored, ToolCallPart)
    assert stored.id == "unique-id-42"
    assert stored.tool_name == "run_command"
    assert stored.args == {"cmd": "ls -la", "cwd": "/home"}


def test_add_tool_result_message_single_part() -> None:
    """add_tool_result_message with one ToolResultPart creates a user-role message."""
    from velix_agent.core.message import ToolResultPart

    tr = ToolResultPart(tool_name="read_file", data="file contents", tool_call_id="tc-001")

    ctx = ConversationContext()
    ctx.add_tool_result_message([tr])

    messages = ctx.get_messages()
    assert len(messages) == 1
    msg = messages[0]
    assert msg.role == "user"
    assert len(msg.content) == 1
    assert isinstance(msg.content[0], ToolResultPart)


def test_add_tool_result_message_multiple_parts() -> None:
    """add_tool_result_message with several ToolResultParts stores all of them."""
    from velix_agent.core.message import ToolResultPart

    tr1 = ToolResultPart(tool_name="tool_a", data="result_a", tool_call_id="id_a")
    tr2 = ToolResultPart(tool_name="tool_b", error="boom", tool_call_id="id_b")

    ctx = ConversationContext()
    ctx.add_tool_result_message([tr1, tr2])

    messages = ctx.get_messages()
    assert len(messages) == 1
    msg = messages[0]
    assert msg.role == "user"
    assert len(msg.content) == 2


def test_add_tool_result_message_preserves_fields() -> None:
    """tool_call_id, tool_name, data, and error are preserved exactly."""
    from velix_agent.core.message import ToolResultPart

    tr_ok = ToolResultPart(
        tool_name="calculator", data={"result": 42}, tool_call_id="call-ok"
    )
    tr_err = ToolResultPart(
        tool_name="network_fetch", error="timeout", tool_call_id="call-err"
    )

    ctx = ConversationContext()
    ctx.add_tool_result_message([tr_ok, tr_err])

    content = ctx.get_messages()[0].content

    ok_part = content[0]
    assert isinstance(ok_part, ToolResultPart)
    assert ok_part.tool_call_id == "call-ok"
    assert ok_part.tool_name == "calculator"
    assert ok_part.data == {"result": 42}
    assert ok_part.error is None

    err_part = content[1]
    assert isinstance(err_part, ToolResultPart)
    assert err_part.tool_call_id == "call-err"
    assert err_part.tool_name == "network_fetch"
    assert err_part.data is None
    assert err_part.error == "timeout"
