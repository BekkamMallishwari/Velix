"""Models for Task Planning."""

from dataclasses import dataclass, field
from enum import StrEnum


class StepStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass
class TaskStep:
    step_id: str
    title: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    failure_criteria: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    context: str = ""
    retry_context: str = ""
    status: StepStatus = StepStatus.PENDING

    def __post_init__(self) -> None:
        if not self.step_id or len(self.step_id) > 50:
            raise ValueError("step_id must be 1-50 characters")
        if not self.title or len(self.title) > 200:
            raise ValueError("title must be 1-200 characters")
        if len(self.description) > 2000:
            raise ValueError("description exceeds 2000 characters")
        if len(self.context) > 2000:
            raise ValueError("context exceeds 2000 characters")
        if len(self.retry_context) > 8000:
            raise ValueError("retry_context exceeds 8000 characters")
        if len(self.dependencies) > 20:
            raise ValueError("Too many dependencies")
        if len(self.success_criteria) > 10:
            raise ValueError("Too many success_criteria")
        if len(self.failure_criteria) > 10:
            raise ValueError("Too many failure_criteria")


@dataclass
class TaskPlan:
    goal: str
    steps: list[TaskStep] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.goal or len(self.goal) > 1000:
            raise ValueError("goal must be 1-1000 characters")
        if not self.steps:
            raise ValueError("TaskPlan must have at least one step")
        if len(self.steps) > 20:
            raise ValueError("TaskPlan exceeds maximum 20 steps")
        if len(self.constraints) > 20:
            raise ValueError("Too many constraints")
        if len(self.assumptions) > 20:
            raise ValueError("Too many assumptions")

        step_ids = set()
        for step in self.steps:
            if step.step_id in step_ids:
                raise ValueError(f"Duplicate step ID: {step.step_id}")
            step_ids.add(step.step_id)
            if step.step_id in step.dependencies:
                raise ValueError(f"Self dependency found in step: {step.step_id}")

        for step in self.steps:
            for dep in step.dependencies:
                if dep not in step_ids:
                    raise ValueError(f"Invalid dependency '{dep}' in step '{step.step_id}'")

        # Check for circular dependencies using DFS
        visited: dict[str, int] = {}
        step_dict = {step.step_id: step for step in self.steps}

        def dfs(node_id: str) -> None:
            if visited.get(node_id) == 0:
                raise ValueError("Circular dependency detected")
            if visited.get(node_id) == 1:
                return

            visited[node_id] = 0
            for dep in step_dict[node_id].dependencies:
                dfs(dep)
            visited[node_id] = 1

        for step in self.steps:
            if step.step_id not in visited:
                dfs(step.step_id)
