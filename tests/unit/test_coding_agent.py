"""Tests for CodingAgent boundary."""

from typing import Any
import pytest

from velix_agent.analysis.models import ResultClassification
from velix_agent.core.agent import Agent
from velix_agent.core.coding_agent import CodingAgent
from velix_agent.core.message import Message, TextPart, ToolResultPart
from velix_agent.core.response import AgentResponse
from velix_agent.planning.models import TaskStep


class MockAgent:
    def __init__(self, turns: list[Any]) -> None:
        self.turns = turns
        self.turn_count = 0
        self.memory_injections: list[tuple[str, list[Any]]] = []

    def _inject_project_memory(self, user_input: str, parts: list[Any]) -> None:
        self.memory_injections.append((user_input, parts))
        parts.append("memory_injected")

    def execute_turn(self, new_messages: list[Message]) -> AgentResponse | None:
        if self.turn_count >= len(self.turns):
            return AgentResponse(text="", status="success")

        turn = self.turns[self.turn_count]
        self.turn_count += 1

        if isinstance(turn, AgentResponse):
            return turn

        if isinstance(turn, ToolResultPart):
            new_messages.append(Message(role="user", content=[turn]))
            return None

        return None

def test_coding_agent_successful_step() -> None:
    # LLM gives final response immediately
    agent = MockAgent([AgentResponse(text="Done", status="success")])
    coding_agent = CodingAgent(agent) # type: ignore

    step = TaskStep(step_id="1", title="test", description="test")
    res = coding_agent.execute_step(step)

    assert res.step_id == "1"
    assert res.analysis is not None
    assert res.analysis.classification == ResultClassification.SUCCESS
    assert agent.turn_count == 1

def test_coding_agent_tool_error_aborts() -> None:
    # LLM calls tool, tool returns error
    turn = ToolResultPart(tool_name="run_command", tool_call_id="1", error="Command failed")
    agent = MockAgent([turn])
    coding_agent = CodingAgent(agent) # type: ignore

    step = TaskStep(step_id="1", title="test", description="test")
    res = coding_agent.execute_step(step)

    assert res.analysis is not None
    assert res.analysis.classification == ResultClassification.RETRYABLE_FAILURE
    assert res.error == "Command failed"
    # It aborted after 1 turn
    assert agent.turn_count == 1

def test_coding_agent_run_command_failure_aborts() -> None:
    # Tool returns data but exit_code != 0
    turn = ToolResultPart(
        tool_name="run_command",
        tool_call_id="1",
        data={"exit_code": 1, "stdout": "", "stderr": "command not found"}
    )
    agent = MockAgent([turn])
    coding_agent = CodingAgent(agent) # type: ignore

    step = TaskStep(step_id="1", title="test", description="test")
    res = coding_agent.execute_step(step)

    assert res.analysis is not None
    assert res.analysis.classification == ResultClassification.RETRYABLE_FAILURE
    assert agent.turn_count == 1

def test_coding_agent_timeout() -> None:
    # LLM makes successful tool calls endlessly (exceeds MAX_STEPS = 5)
    turn = ToolResultPart(
        tool_name="list_directory",
        tool_call_id="1",
        data={"items": []}
    )
    # Give it 10 turns of successful tool calls
    agent = MockAgent([turn] * 10)
    coding_agent = CodingAgent(agent) # type: ignore

    step = TaskStep(step_id="1", title="test", description="test")
    res = coding_agent.execute_step(step)

    assert res.analysis is not None
    assert res.analysis.classification == ResultClassification.TIMEOUT
    assert agent.turn_count == 5  # Internal MAX_STEPS is 5

def test_coding_agent_memory_injection() -> None:
    agent = MockAgent([AgentResponse(text="Done", status="success")])
    coding_agent = CodingAgent(agent) # type: ignore

    step = TaskStep(step_id="1", title="memtest", description="memtest")
    coding_agent.execute_step(step)

    assert len(agent.memory_injections) == 1
    user_input, parts = agent.memory_injections[0]
    assert "memtest" in user_input
    assert "memory_injected" in parts
