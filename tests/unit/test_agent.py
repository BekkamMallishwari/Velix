"""Unit tests for the Agent Core."""

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
