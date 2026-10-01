"""Unit tests for the Agent Core."""

from typing import Any

from velix_agent.core.agent import Agent
from velix_agent.core.session import Session
from velix_agent.providers.mock import MockProvider


def test_agent_empty_input() -> None:
    """Test that agent handles empty input."""
    session = Session.create()
    agent = Agent(session, provider=MockProvider())
    response = agent.respond("   ")
    assert response.status == "error"
    assert "Empty" in str(response.error)
    assert len(session.context.get_messages()) == 0


def test_agent_valid_input() -> None:
    """Test that agent handles valid input and updates context."""
    session = Session.create()
    agent = Agent(session, provider=MockProvider())

    response = agent.respond("What is VelixAgent?")
    assert response.status == "success"
    assert "VelixAgent is an AI coding agent" in response.text

    messages = session.context.get_messages()
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content[0].text == "What is VelixAgent?"
    assert messages[1].role == "assistant"
    assert messages[1].content[0].text == response.text


def test_agent_unknown_prompt() -> None:
    """Test that agent returns the mock fallback for unknown prompts."""
    session = Session.create()
    agent = Agent(session, provider=MockProvider())

    response = agent.respond("Solve the Riemann hypothesis")
    assert response.status == "success"
    assert "VelixAgent Phase 4 is active" in response.text


def test_agent_with_tool_registry() -> None:
    """Test that agent can be created with and access a tool registry."""
    from velix_agent.tools.registry import ToolRegistry

    registry = ToolRegistry()
    session = Session.create()
    agent = Agent(session, provider=MockProvider(), tool_registry=registry)

    assert agent.tool_registry is registry


def test_agent_default_tool_registry() -> None:
    """Test that agent creates a default tool registry if none provided."""
    session = Session.create()
    agent = Agent(session, provider=MockProvider())

    assert agent.tool_registry is not None
    from velix_agent.tools.registry import ToolRegistry

    assert isinstance(agent.tool_registry, ToolRegistry)


def test_runtime_injects_tools() -> None:
    """Test that Runtime.__post_init__ injects the correct tools into the agent."""
    from velix_agent.core.runtime import Runtime
    from velix_agent.sandbox.manager import SandboxManager

    runtime = Runtime.create()
    agent = runtime.agent
    registry = agent.tool_registry

    assert registry is not None

    read_file = registry.get_tool("read_file")
    assert read_file is not None

    list_dir = registry.get_tool("list_directory")
    assert list_dir is not None

    run_cmd = registry.get_tool("run_command")
    assert run_cmd is not None

    # Verify sandbox is preserved
    assert hasattr(run_cmd, "sandbox")
    assert isinstance(run_cmd.sandbox, SandboxManager)


def test_agent_tool_error_recovery() -> None:
    """Test that agent continues executing tools after a tool error."""
    from typing import Any

    from velix_agent.core.message import Message, ToolCallPart, ToolResultPart
    from velix_agent.core.response import AgentResponse
    from velix_agent.providers.base import Provider
    from velix_agent.tools.base import Tool, ToolResult
    from velix_agent.tools.registry import ToolRegistry

    class SequentialProvider(Provider):
        def __init__(self) -> None:
            self.call_count = 0
            self.history: list[list[Message]] = []

        def generate(
            self, messages: list[Message], tools: list[Tool] | None = None
        ) -> AgentResponse:
            self.call_count += 1
            self.history.append(messages)
            if self.call_count == 1:
                return AgentResponse(
                    text="Calling tool 1",
                    status="success",
                    tool_calls=[
                        ToolCallPart(
                            tool_name="fake_tool", args={"action": "succeed_1"}, id="call_1"
                        )
                    ],
                )
            elif self.call_count == 2:
                return AgentResponse(
                    text="Calling tool 2",
                    status="success",
                    tool_calls=[
                        ToolCallPart(tool_name="fake_tool", args={"action": "fail_2"}, id="call_2")
                    ],
                )
            elif self.call_count == 3:
                return AgentResponse(
                    text="Calling tool 3",
                    status="success",
                    tool_calls=[
                        ToolCallPart(
                            tool_name="fake_tool", args={"action": "succeed_3"}, id="call_3"
                        )
                    ],
                )
            else:
                return AgentResponse(text="Done", status="success")

    class FakeTool(Tool):
        def __init__(self) -> None:
            self.calls: list[str] = []

        @property
        def name(self) -> str:
            return "fake_tool"

        @property
        def description(self) -> str:
            return "Fake tool"

        @property
        def parameters(self) -> dict[str, Any]:
            return {
                "type": "object",
                "properties": {"action": {"type": "string"}},
                "required": ["action"],
            }

        def execute(self, **kwargs: Any) -> ToolResult:
            action = kwargs.get("action", "")
            self.calls.append(action)
            if action == "fail_2":
                return ToolResult(status="error", error="Intentional failure")
            return ToolResult(status="success", data=f"Success {action}")

    fake_tool = FakeTool()
    registry = ToolRegistry()
    registry.register(fake_tool)

    session = Session.create()
    provider = SequentialProvider()
    agent = Agent(session, provider=provider, tool_registry=registry)

    response = agent.respond("Start tool sequence")

    # Assert final response
    assert response.status == "success"
    assert response.text == "Done"

    # Assert provider called exactly 4 times
    assert provider.call_count == 4

    # Assert tool executed exactly 3 times in correct order
    assert len(fake_tool.calls) == 3
    assert fake_tool.calls == ["succeed_1", "fail_2", "succeed_3"]

    # Verify that the tool error was properly fed back into the context
    context_msgs = session.context.get_messages()

    # Check that there is a ToolResultPart with error="Intentional failure"
    found_error_part = False
    for msg in context_msgs:
        if msg.role == "user" and isinstance(msg.content, list):
            for part in msg.content:
                if isinstance(part, ToolResultPart) and part.error == "Intentional failure":
                    found_error_part = True
                    break

    assert found_error_part, "Expected to find the failed tool result fed back to the context"


def test_agent_tool_logging_success(caplog: Any) -> None:
    """Test that successful tool executions are logged correctly without exposing secrets."""
    import logging

    from velix_agent.core.message import Message, ToolCallPart
    from velix_agent.core.response import AgentResponse
    from velix_agent.providers.base import Provider
    from velix_agent.tools.base import Tool, ToolResult
    from velix_agent.tools.registry import ToolRegistry

    class SingleToolProvider(Provider):
        def __init__(self) -> None:
            self.called = False

        def generate(
            self, messages: list[Message], tools: list[Tool] | None = None
        ) -> AgentResponse:
            if not self.called:
                self.called = True
                return AgentResponse(
                    text="Calling tool",
                    status="success",
                    tool_calls=[
                        ToolCallPart(
                            tool_name="test_tool",
                            args={"secret_key": "super_secret_123"},
                            id="call_999",
                        )
                    ],
                )
            return AgentResponse(text="Done", status="success")

    class TestTool(Tool):
        @property
        def name(self) -> str:
            return "test_tool"

        @property
        def description(self) -> str:
            return "Test tool"

        @property
        def parameters(self) -> dict[str, Any]:
            return {"type": "object", "properties": {"secret_key": {"type": "string"}}}

        def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(status="success", data="Done")

    registry = ToolRegistry()
    registry.register(TestTool())
    session = Session.create()
    agent = Agent(session, provider=SingleToolProvider(), tool_registry=registry)

    from unittest.mock import patch

    with (
        patch("time.perf_counter", side_effect=[100.0, 101.5]),
        caplog.at_level(logging.DEBUG, logger="velix_agent.agent"),
    ):
        agent.respond("Test logging")

    # Assert success log is present
    logs = [rec.message for rec in caplog.records if "Tool execution:" in rec.message]
    assert len(logs) == 1
    msg = logs[0]

    assert "name=test_tool" in msg
    assert "id=call_999" in msg
    assert "status=success" in msg
    assert "duration=1.500s" in msg
    assert "super_secret_123" not in msg


def test_agent_tool_logging_error(caplog: Any) -> None:
    """Test that failed tool executions log the error."""
    import logging

    from velix_agent.core.message import Message, ToolCallPart
    from velix_agent.core.response import AgentResponse
    from velix_agent.providers.base import Provider
    from velix_agent.tools.base import Tool, ToolResult
    from velix_agent.tools.registry import ToolRegistry

    class ErrorToolProvider(Provider):
        def __init__(self) -> None:
            self.called = False

        def generate(
            self, messages: list[Message], tools: list[Tool] | None = None
        ) -> AgentResponse:
            if not self.called:
                self.called = True
                return AgentResponse(
                    text="Calling error tool",
                    status="success",
                    tool_calls=[
                        ToolCallPart(
                            tool_name="error_tool", args={"param": "value"}, id="call_error"
                        )
                    ],
                )
            return AgentResponse(text="Done", status="success")

    class ErrorTool(Tool):
        @property
        def name(self) -> str:
            return "error_tool"

        @property
        def description(self) -> str:
            return "Error tool"

        @property
        def parameters(self) -> dict[str, Any]:
            return {"type": "object", "properties": {"param": {"type": "string"}}}

        def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(status="error", error="A predictable failure.")

    registry = ToolRegistry()
    registry.register(ErrorTool())
    session = Session.create()
    agent = Agent(session, provider=ErrorToolProvider(), tool_registry=registry)

    from unittest.mock import patch

    with (
        patch("time.perf_counter", side_effect=[100.0, 102.5]),
        caplog.at_level(logging.DEBUG, logger="velix_agent.agent"),
    ):
        agent.respond("Test error logging")

    # Assert error log is present
    logs = [rec.message for rec in caplog.records if "Tool execution:" in rec.message]
    assert len(logs) == 1
    msg = logs[0]

    assert "name=error_tool" in msg
    assert "id=call_error" in msg
    assert "status=error" in msg
    assert "duration=2.500s" in msg
    assert "'A predictable failure.'" in msg
