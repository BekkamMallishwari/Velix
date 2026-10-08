import pytest

from velix_agent.planning.models import TaskPlan, TaskStep


def test_task_step_validation() -> None:
    # Valid
    step = TaskStep(step_id="1", title="title", description="desc")
    assert step.step_id == "1"

    # Too long ID
    with pytest.raises(ValueError, match="step_id must be 1-50 characters"):
        TaskStep(step_id="a" * 51, title="title", description="desc")

    # Too long title
    with pytest.raises(ValueError, match="title must be 1-200 characters"):
        TaskStep(step_id="1", title="a" * 201, description="desc")

    # Too many dependencies
    with pytest.raises(ValueError, match="Too many dependencies"):
        TaskStep(step_id="1", title="title", description="desc", dependencies=["dep"] * 21)


def test_task_plan_validation() -> None:
    step1 = TaskStep(step_id="1", title="s1", description="d")
    step2 = TaskStep(step_id="2", title="s2", description="d", dependencies=["1"])

    # Valid
    plan = TaskPlan(goal="goal", steps=[step1, step2])
    plan.validate()

    # Empty steps
    with pytest.raises(ValueError, match="TaskPlan must have at least one step"):
        TaskPlan(goal="goal", steps=[]).validate()

    # Duplicate IDs
    with pytest.raises(ValueError, match="Duplicate step ID: 1"):
        TaskPlan(goal="goal", steps=[step1, step1]).validate()

    # Invalid dependency
    step3 = TaskStep(step_id="3", title="s3", description="d", dependencies=["999"])
    with pytest.raises(ValueError, match="Invalid dependency '999' in step '3'"):
        TaskPlan(goal="goal", steps=[step3]).validate()

    # Self dependency
    step_self = TaskStep(step_id="1", title="s1", description="d", dependencies=["1"])
    with pytest.raises(ValueError, match="Self dependency found in step: 1"):
        TaskPlan(goal="goal", steps=[step_self]).validate()

    # Circular dependency
    stepA = TaskStep(step_id="A", title="A", description="d", dependencies=["B"])
    stepB = TaskStep(step_id="B", title="B", description="d", dependencies=["A"])
    with pytest.raises(ValueError, match="Circular dependency detected"):
        TaskPlan(goal="goal", steps=[stepA, stepB]).validate()
