from pathlib import Path

from velix_agent.core.agent import Agent
from velix_agent.core.config import VelixConfig
from velix_agent.core.response import AgentResponse
from velix_agent.core.session import Session
from velix_agent.memory.store import MemoryManager
from velix_agent.providers.base import Provider


class MockProvider(Provider):
    def __init__(self) -> None:
        self.received_context = []

    def generate(self, context, tools=None):
        self.received_context = context
        return AgentResponse(text="Mock response", status="success")

    def count_tokens(self, text: str) -> int:
        return 0


def test_passive_memory_injection(tmp_path: Path) -> None:
    mm = MemoryManager(workspace_root=tmp_path)
    mm.initialize_db()
    mm.store("project_fact", "Fact 1", "This is the first fact")
    mm.store("project_fact", "Fact 2", "This is the second fact")
    mm.store("task_hindsight", "Task 1", "This is hindsight")

    config = VelixConfig(enable_memory=True)
    session = Session.create()
    provider = MockProvider()
    agent = Agent(session=session, provider=provider, config=config, memory_manager=mm)

    agent.respond("Fact")

    # Check that passive memory was injected into the context
    context = provider.received_context
    assert len(context) > 0
    # The last message is the user message
    user_msg = context[-1]

    # It should have 2 parts: the injected memory and the user input
    assert len(user_msg.content) >= 2
    injected_part = user_msg.content[0]

    assert "<project_historical_memory>" in injected_part.text
    assert "Fact 1" in injected_part.text
    # Hindsight shouldn't be included as we only filter project_fact
    assert "hindsight" not in injected_part.text


def test_passive_memory_disabled(tmp_path: Path) -> None:
    mm = MemoryManager(workspace_root=tmp_path)
    mm.initialize_db()
    mm.store("project_fact", "Fact 1", "This is the first fact")

    config = VelixConfig(enable_memory=False)
    session = Session.create()
    provider = MockProvider()
    agent = Agent(session=session, provider=provider, config=config, memory_manager=mm)

    agent.respond("Fact")

    context = provider.received_context
    user_msg = context[-1]

    # Should not have memory injected
    assert len(user_msg.content) == 1
    assert "<project_historical_memory>" not in user_msg.content[0].text


def test_passive_memory_empty(tmp_path: Path) -> None:
    mm = MemoryManager(workspace_root=tmp_path)
    mm.initialize_db()

    config = VelixConfig(enable_memory=True)
    session = Session.create()
    provider = MockProvider()
    agent = Agent(session=session, provider=provider, config=config, memory_manager=mm)

    agent.respond("Hello")

    context = provider.received_context
    user_msg = context[-1]

    # Should not have memory injected if empty
    assert len(user_msg.content) == 1
    assert "<project_historical_memory>" not in user_msg.content[0].text
