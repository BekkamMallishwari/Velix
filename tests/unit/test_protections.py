"""Tests for agent protections."""

import pytest
from velix_agent.core.message import Message, ToolCallPart
from velix_agent.core.protections import RepeatedActionDetector


def test_normalization() -> None:
    args1 = {"b": 2, "a": 1}
    args2 = {"a": 1, "b": 2}
    
    norm1 = RepeatedActionDetector._normalize_args(args1)
    norm2 = RepeatedActionDetector._normalize_args(args2)
    
    assert norm1 == norm2
    assert '{"a": 1, "b": 2}' == norm1

def test_unserializable_args() -> None:
    class Unserializable:
        pass
    
    args = {"obj": Unserializable()}
    norm = RepeatedActionDetector._normalize_args(args)
    assert "Unserializable" in norm

def test_repeated_calls_identical() -> None:
    msg1 = Message(role="assistant", content=[
        ToolCallPart(tool_name="test_tool", args={"a": 1}, id="1")
    ])
    msg2 = Message(role="assistant", content=[
        ToolCallPart(tool_name="test_tool", args={"a": 1}, id="2")
    ])
    msg3 = Message(role="assistant", content=[
        ToolCallPart(tool_name="test_tool", args={"a": 1}, id="3")
    ])
    
    target = ToolCallPart(tool_name="test_tool", args={"a": 1}, id="4")
    
    # 0 previous
    assert not RepeatedActionDetector.check_repeated_calls([], target, limit=3)
    # 1 previous
    assert not RepeatedActionDetector.check_repeated_calls([msg1], target, limit=3)
    # 2 previous
    assert not RepeatedActionDetector.check_repeated_calls([msg1, msg2], target, limit=3)
    # 3 previous -> blocks on the 4th attempt
    assert RepeatedActionDetector.check_repeated_calls([msg1, msg2, msg3], target, limit=3)

def test_repeated_calls_different_args() -> None:
    msg1 = Message(role="assistant", content=[
        ToolCallPart(tool_name="test_tool", args={"a": 1}, id="1")
    ])
    msg2 = Message(role="assistant", content=[
        ToolCallPart(tool_name="test_tool", args={"a": 2}, id="2")
    ])
    msg3 = Message(role="assistant", content=[
        ToolCallPart(tool_name="test_tool", args={"a": 3}, id="3")
    ])
    
    target = ToolCallPart(tool_name="test_tool", args={"a": 1}, id="4")
    
    # Only 1 previous identical (msg1)
    assert not RepeatedActionDetector.check_repeated_calls([msg1, msg2, msg3], target, limit=3)

def test_repeated_calls_different_tool() -> None:
    msg1 = Message(role="assistant", content=[
        ToolCallPart(tool_name="other_tool", args={"a": 1}, id="1")
    ])
    msg2 = Message(role="assistant", content=[
        ToolCallPart(tool_name="other_tool", args={"a": 1}, id="2")
    ])
    msg3 = Message(role="assistant", content=[
        ToolCallPart(tool_name="other_tool", args={"a": 1}, id="3")
    ])
    
    target = ToolCallPart(tool_name="test_tool", args={"a": 1}, id="4")
    
    # 0 previous identical for test_tool
    assert not RepeatedActionDetector.check_repeated_calls([msg1, msg2, msg3], target, limit=3)

def test_repeated_calls_ignores_self() -> None:
    # If the messages array already contains the target call (same ID), it shouldn't count it as a *previous* call
    target = ToolCallPart(tool_name="test_tool", args={"a": 1}, id="1")
    msg1 = Message(role="assistant", content=[target])
    
    # 0 previous, 1 current
    assert not RepeatedActionDetector.check_repeated_calls([msg1], target, limit=1)

def test_agent_aborts_on_repeated_tool() -> None:
    from velix_agent.core.agent import Agent
    from velix_agent.core.session import Session
    from velix_agent.core.response import AgentResponse
    from velix_agent.tools.registry import ToolRegistry
    
    class FakeProvider:
        def generate(self, messages, tools):
            # We just return a tool call
            return AgentResponse(
                text="",
                status="success", 
                tool_calls=[ToolCallPart(tool_name="fake_tool", args={"x": 1}, id="test_id")]
            )

    registry = ToolRegistry()
    class FakeTool:
        name = "fake_tool"
        def execute(self, **kwargs):
            return type("ToolResult", (), {"status": "success", "data": "ok", "error": None, "metadata": {}})()
    registry.register(FakeTool())
    
    agent = Agent(session=Session(), provider=FakeProvider(), tool_registry=registry)
    
    # Simulate a history where 'fake_tool' was called 3 times previously with x=1
    messages = [
        Message(role="assistant", content=[ToolCallPart(tool_name="fake_tool", args={"x": 1}, id=f"test_id_{i}")]) for i in range(3)
    ]
    
    # The execute_turn call will call the provider, which returns another fake_tool({"x": 1})
    res = agent.execute_turn(messages)
    
    # It should not return a response yet, it appends to messages
    assert res is None
    
    # The last message appended by agent should be the user message with ToolResultPart
    last_msg = messages[-1]
    assert last_msg.role == "user"
    assert len(last_msg.content) == 1
    
    result_part = last_msg.content[0]
    assert "Repeated tool call limit reached" in result_part.error

