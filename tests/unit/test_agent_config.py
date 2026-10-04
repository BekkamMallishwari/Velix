"""Tests for Agent configuration ownership."""

from typing import Any
from unittest.mock import patch

from velix_agent.core.agent import Agent
from velix_agent.core.config import VelixConfig
from velix_agent.core.session import Session
from velix_agent.providers.mock import MockProvider


def test_agent_uses_injected_config() -> None:
    """Test that Agent uses the injected configuration."""
    session = Session.create()
    custom_config = VelixConfig(max_input_file_size=9999)
    agent = Agent(session, provider=MockProvider(), config=custom_config)

    assert agent.config is custom_config
    assert agent.config.max_input_file_size == 9999


def test_agent_does_not_recreate_config() -> None:
    """Test that Agent does not recreate configuration on every respond() call."""
    session = Session.create()
    custom_config = VelixConfig()
    agent = Agent(session, provider=MockProvider(), config=custom_config)

    with patch("velix_agent.core.config.VelixConfig") as mock_config:
        agent.respond("Test message 1")
        agent.respond("Test message 2")
        # VelixConfig should not be instantiated during respond
        mock_config.assert_not_called()


def test_agent_sequential_responds() -> None:
    """Test that two sequential respond() calls work with the same Agent."""
    session = Session.create()
    agent = Agent(session, provider=MockProvider())

    response1 = agent.respond("First message")
    assert response1.status == "success"

    response2 = agent.respond("Second message")
    assert response2.status == "success"

    messages = session.context.get_messages()
    # 2 user messages, 2 assistant responses
    assert len(messages) == 4
    assert messages[0].content[0].text == "First message"
    assert messages[2].content[0].text == "Second message"


def test_agent_uses_config_for_truncation() -> None:
    """Test that existing tool execution behavior remains unchanged and uses config."""
    from velix_agent.core.message import Message, ToolCallPart, ToolResultPart
    from velix_agent.core.response import AgentResponse
    from velix_agent.providers.base import Provider
    from velix_agent.tools.base import Tool, ToolResult
    from velix_agent.tools.registry import ToolRegistry

    class TruncateProvider(Provider):
        def generate(
            self, messages: list[Message], tools: list[Tool] | None = None
        ) -> AgentResponse:
            if any(
                isinstance(msg.content, list)
                and any(isinstance(p, ToolResultPart) for p in msg.content)
                for msg in messages
            ):
                return AgentResponse(text="Done", status="success")
            return AgentResponse(
                text="Calling tool",
                status="success",
                tool_calls=[ToolCallPart(tool_name="long_tool", args={}, id="call_1")],
            )

    class LongTool(Tool):
        @property
        def name(self) -> str:
            return "long_tool"

        @property
        def description(self) -> str:
            return "Tool returning long data"

        @property
        def parameters(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}}

        def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(status="success", data="A" * 1000)

    registry = ToolRegistry()
    registry.register(LongTool())

    session = Session.create()
    custom_config = VelixConfig(max_tool_output_size=100)
    agent = Agent(
        session, provider=TruncateProvider(), tool_registry=registry, config=custom_config
    )

    agent.respond("Trigger tool")

    messages = session.context.get_messages()
    # Find the tool result message
    tool_result_part = None
    for msg in messages:
        if msg.role == "user" and isinstance(msg.content, list):
            for part in msg.content:
                if isinstance(part, ToolResultPart):
                    tool_result_part = part

    assert tool_result_part is not None
    assert isinstance(tool_result_part.data, str)

    # Verify exact truncation behavior from _truncate_tool_result.
    # The default max_tool_output_size is much larger than 1000,
    # so if it used a default config, length would be 1000.
    # Because we injected max_tool_output_size=100, it must be exactly 100.
    assert len(tool_result_part.data) == 100
    assert tool_result_part.data.endswith("\n...[Output truncated due to size limit]...\n")
