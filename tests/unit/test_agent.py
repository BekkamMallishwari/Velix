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
