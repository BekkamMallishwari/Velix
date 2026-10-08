import json
from typing import Any, Literal

import pytest

from velix_agent.core.response import AgentResponse
from velix_agent.planning.models import TaskPlan
from velix_agent.planning.planner import InvalidPlanError, PlanningError, TaskPlanner
from velix_agent.providers.base import Provider


class MockProvider(Provider):
    def __init__(self, response_text: str, status: Literal["success", "error"] = "success") -> None:
        self.response_text = response_text
        self.status = status
        self.received_context: list[Any] = []

    def generate(self, context: Any, tools: Any = None) -> AgentResponse:
        self.received_context = context
        if self.status == "error":
            return AgentResponse(text="", status="error", error="Mock error")
        return AgentResponse(text=self.response_text, status="success")

    def count_tokens(self, text: str) -> int:
        return 0


def test_planner_simple_request() -> None:
    plan_json = {
        "goal": "Test goal",
        "steps": [
            {
                "step_id": "1",
                "title": "First step",
                "description": "Do something",
                "dependencies": [],
                "success_criteria": ["done"],
            }
        ],
        "constraints": ["none"],
        "assumptions": ["none"],
    }
    provider = MockProvider(response_text=json.dumps(plan_json))
    planner = TaskPlanner(provider=provider)

    plan = planner.create_plan("Do something")

    assert isinstance(plan, TaskPlan)
    assert plan.goal == "Test goal"
    assert len(plan.steps) == 1
    assert plan.steps[0].step_id == "1"


def test_planner_empty_request() -> None:
    planner = TaskPlanner(provider=MockProvider(""))
    with pytest.raises(InvalidPlanError, match=r"Empty request cannot be planned\."):
        planner.create_plan("   ")


def test_planner_malformed_json() -> None:
    provider = MockProvider(response_text="This is not JSON")
    planner = TaskPlanner(provider=provider)
    with pytest.raises(InvalidPlanError, match="Failed to parse JSON plan"):
        planner.create_plan("Request")


def test_planner_provider_error() -> None:
    provider = MockProvider(response_text="", status="error")
    planner = TaskPlanner(provider=provider)
    with pytest.raises(PlanningError, match="Provider failed"):
        planner.create_plan("Request")


def test_planner_complex_request_with_markdown_json() -> None:
    plan_json = {
        "goal": "Test goal",
        "steps": [
            {"step_id": "step_1", "title": "Step 1"},
            {"step_id": "step_2", "title": "Step 2", "dependencies": ["step_1"]},
        ],
    }
    resp = f"Here is the plan:\n```json\n{json.dumps(plan_json)}\n```\nGood luck!"
    provider = MockProvider(response_text=resp)
    planner = TaskPlanner(provider=provider)

    plan = planner.create_plan("Complex req")
    assert len(plan.steps) == 2
    assert plan.steps[1].dependencies == ["step_1"]


def test_planner_too_many_steps() -> None:
    plan_json = {
        "goal": "Goal",
        "steps": [{"step_id": str(i), "title": "t", "description": "d"} for i in range(25)],
    }
    provider = MockProvider(response_text=json.dumps(plan_json))
    planner = TaskPlanner(provider=provider)
    with pytest.raises(InvalidPlanError, match="TaskPlan exceeds maximum 20 steps"):
        planner.create_plan("Too big")
