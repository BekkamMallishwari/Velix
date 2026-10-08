"""Tests for the autonomous coding loop."""

import pytest
from typing import Any

from velix_agent.core.agent import Agent
from velix_agent.core.application import AutonomousCodingLoop
from velix_agent.core.message import ToolCallPart
from velix_agent.core.response import AgentResponse
from velix_agent.core.session import Session
from velix_agent.orchestrator.models import OrchestratorState
from velix_agent.planning.models import TaskPlan, TaskStep


class FakeProvider:
    def __init__(self, responses: list[AgentResponse]) -> None:
        self.responses = responses
        self.call_count = 0
        self.prompts: list[str] = []

    def generate(self, messages: list[Any], tools: Any = None) -> AgentResponse:
        content = messages[-1].content
        if isinstance(content, list) and len(content) > 0:
            if hasattr(content[0], "text"):
                self.prompts.append(content[0].text)
        
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return AgentResponse(status="success", text="fallback")


class FakePlanner:
    def __init__(self, plan: TaskPlan | Exception, runtime_manager: Any = None, sandbox_manager: Any = None) -> None:
        self.plan = plan
        self.runtime_manager = runtime_manager
        self.sandbox_manager = sandbox_manager

    def create_plan(self, user_request: str) -> TaskPlan:
        if isinstance(self.plan, Exception):
            raise self.plan
        return self.plan


def test_autonomous_loop_success() -> None:
    plan = TaskPlan(
        goal="test",
        steps=[
            TaskStep(step_id="1", title="1", description="desc1"),
            TaskStep(step_id="2", title="2", description="desc2", dependencies=["1"]),
        ],
    )
    planner = FakePlanner(plan)

    provider = FakeProvider([
        AgentResponse(status="success", text="done step 1"),
        AgentResponse(status="success", text="done step 2"),
    ])
    agent = Agent(Session(), provider=provider)  # type: ignore

    loop = AutonomousCodingLoop(agent=agent, planner=planner)  # type: ignore
    state = loop.run("do things")

    assert state == OrchestratorState.COMPLETED
    assert provider.call_count == 2


def test_autonomous_loop_retry_context() -> None:
    plan = TaskPlan(
        goal="test",
        steps=[
            TaskStep(step_id="1", title="1", description="desc1"),
        ],
    )
    planner = FakePlanner(plan)

    provider = FakeProvider([
        # Attempt 1: calls unknown tool -> fails
        AgentResponse(
            text="",
            status="success",
            tool_calls=[ToolCallPart(tool_name="bad_tool", args={}, id="1")],
        ),
        # Attempt 2: succeeds
        AgentResponse(status="success", text="fixed"),
    ])
    agent = Agent(Session(), provider=provider)  # type: ignore
    loop = AutonomousCodingLoop(agent=agent, planner=planner)  # type: ignore

    state = loop.run("do things")

    assert state == OrchestratorState.COMPLETED
    assert provider.call_count == 2

    # Verify retry context was in the prompt for attempt 2
    prompt2 = provider.prompts[1]
    assert "RETRY CONTEXT:" in prompt2
    assert "Previous attempt 1 failed" in prompt2
    assert "Unknown tool" in prompt2


def test_autonomous_loop_capability_blocking() -> None:
    plan = TaskPlan(
        goal="test",
        steps=[
            TaskStep(step_id="1", title="1", description="desc", required_capabilities=["java"]),
        ],
    )
    planner = FakePlanner(plan)

    provider = FakeProvider([])
    agent = Agent(Session(), provider=provider)  # type: ignore
    loop = AutonomousCodingLoop(agent=agent, planner=planner)  # type: ignore

    state = loop.run("do things")
    assert state == OrchestratorState.BLOCKED


def test_autonomous_loop_dependency_blocking() -> None:
    plan = TaskPlan(
        goal="test",
        steps=[
            TaskStep(step_id="1", title="1", description="desc", required_capabilities=["java"]),
            TaskStep(step_id="2", title="2", description="desc", dependencies=["1"]),
        ],
    )
    planner = FakePlanner(plan)

    provider = FakeProvider([])
    agent = Agent(Session(), provider=provider)  # type: ignore
    loop = AutonomousCodingLoop(agent=agent, planner=planner)  # type: ignore

    state = loop.run("do things")
    # Step 1 is blocked, so Step 2 can never run
    assert state == OrchestratorState.BLOCKED


def test_autonomous_loop_planning_failure() -> None:
    planner = FakePlanner(Exception("Planning failed"))
    agent = Agent(Session(), provider=FakeProvider([]))  # type: ignore
    loop = AutonomousCodingLoop(agent=agent, planner=planner)  # type: ignore

    state = loop.run("do things")
    assert state == OrchestratorState.FAILED
