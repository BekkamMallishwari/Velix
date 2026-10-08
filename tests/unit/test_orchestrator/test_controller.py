"""Tests for Orchestrator controller."""

from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional

from velix_agent.analysis.models import AnalysisResult, ResultClassification
from velix_agent.orchestrator.controller import OrchestratorController
from velix_agent.orchestrator.models import OrchestratorState, StepExecutionResult
from velix_agent.planning.models import TaskPlan, TaskStep


class MockExecutor:
    def __init__(self, results: Dict[str, List[AnalysisResult]]) -> None:
        self.results = results
        self.call_counts: Dict[str, int] = {}

    def execute_step(self, step: TaskStep, budget: Any = None) -> StepExecutionResult:
        self.call_counts[step.step_id] = self.call_counts.get(step.step_id, 0) + 1
        res_list = self.results.get(step.step_id, [])
        if not res_list:
            return StepExecutionResult(step_id=step.step_id, analysis=None)
        
        # Pop the first result and return it
        res = res_list.pop(0)
        return StepExecutionResult(step_id=step.step_id, analysis=res)


def create_mock_analysis(classification: ResultClassification) -> AnalysisResult:
    return AnalysisResult(
        classification=classification,
        reason="mock",
        retryable=classification in (ResultClassification.RETRYABLE_FAILURE, ResultClassification.TIMEOUT),
        security_blocked=classification == ResultClassification.SECURITY_BLOCKED,
        resource_limited=classification == ResultClassification.RESOURCE_LIMIT,
        timeout=classification == ResultClassification.TIMEOUT,
        exit_code=0
    )


def test_initial_state() -> None:
    plan = TaskPlan(goal="Goal", steps=[TaskStep(step_id="1", title="title", description="desc")])
    ctrl = OrchestratorController(plan=plan, executor=MockExecutor({}))
    assert ctrl.context.orchestrator_state == OrchestratorState.READY


def test_successful_step() -> None:
    plan = TaskPlan(goal="Goal", steps=[TaskStep(step_id="1", title="title", description="desc")])
    executor = MockExecutor({"1": [create_mock_analysis(ResultClassification.SUCCESS)]})
    ctrl = OrchestratorController(plan=plan, executor=executor)
    
    ctrl.run()
    assert ctrl.context.orchestrator_state == OrchestratorState.COMPLETED
    assert "1" in ctrl.context.completed_steps
    assert executor.call_counts["1"] == 1


def test_dependency_ordering() -> None:
    step1 = TaskStep(step_id="1", title="title", description="desc")
    step2 = TaskStep(step_id="2", title="title", description="desc", dependencies=["1"])
    plan = TaskPlan(goal="Goal", steps=[step1, step2])
    
    executor = MockExecutor({
        "1": [create_mock_analysis(ResultClassification.SUCCESS)],
        "2": [create_mock_analysis(ResultClassification.SUCCESS)]
    })
    ctrl = OrchestratorController(plan=plan, executor=executor)
    
    ctrl.step()
    assert "1" in ctrl.context.completed_steps
    assert "2" not in ctrl.context.completed_steps
    
    ctrl.run()
    assert "2" in ctrl.context.completed_steps
    assert ctrl.context.orchestrator_state == OrchestratorState.COMPLETED


def test_retryable_failure() -> None:
    step1 = TaskStep(step_id="1", title="title", description="desc")
    plan = TaskPlan(goal="Goal", steps=[step1])
    
    executor = MockExecutor({
        "1": [
            create_mock_analysis(ResultClassification.RETRYABLE_FAILURE),
            create_mock_analysis(ResultClassification.SUCCESS)
        ]
    })
    ctrl = OrchestratorController(plan=plan, executor=executor)
    
    ctrl.step()
    
    ctrl.run()
    assert ctrl.context.orchestrator_state == OrchestratorState.COMPLETED
    assert executor.call_counts["1"] == 2


def test_retry_limit() -> None:
    step1 = TaskStep(step_id="1", title="title", description="desc")
    plan = TaskPlan(goal="Goal", steps=[step1])
    
    executor = MockExecutor({
        "1": [
            create_mock_analysis(ResultClassification.RETRYABLE_FAILURE),
            create_mock_analysis(ResultClassification.RETRYABLE_FAILURE),
            create_mock_analysis(ResultClassification.RETRYABLE_FAILURE),
            create_mock_analysis(ResultClassification.RETRYABLE_FAILURE)
        ]
    })
    # max_step_retries is 2 -> meaning 3 total attempts
    ctrl = OrchestratorController(plan=plan, executor=executor, max_step_retries=2)
    
    ctrl.run()
    assert ctrl.context.orchestrator_state == OrchestratorState.FAILED
    assert "1" in ctrl.context.failed_steps
    assert executor.call_counts["1"] == 3


def test_security_blocked() -> None:
    step1 = TaskStep(step_id="1", title="title", description="desc")
    plan = TaskPlan(goal="Goal", steps=[step1])
    
    executor = MockExecutor({
        "1": [create_mock_analysis(ResultClassification.SECURITY_BLOCKED)]
    })
    ctrl = OrchestratorController(plan=plan, executor=executor)
    
    ctrl.run()
    assert ctrl.context.orchestrator_state == OrchestratorState.BLOCKED
    assert "1" in ctrl.context.blocked_steps
    assert executor.call_counts["1"] == 1


def test_resource_limit() -> None:
    step1 = TaskStep(step_id="1", title="title", description="desc")
    plan = TaskPlan(goal="Goal", steps=[step1])
    
    executor = MockExecutor({
        "1": [create_mock_analysis(ResultClassification.RESOURCE_LIMIT)]
    })
    ctrl = OrchestratorController(plan=plan, executor=executor)
    
    ctrl.run()
    assert ctrl.context.orchestrator_state == OrchestratorState.BLOCKED
    assert "1" in ctrl.context.blocked_steps


def test_non_retryable_failure() -> None:
    step1 = TaskStep(step_id="1", title="title", description="desc")
    plan = TaskPlan(goal="Goal", steps=[step1])
    
    executor = MockExecutor({
        "1": [create_mock_analysis(ResultClassification.NON_RETRYABLE_FAILURE)]
    })
    ctrl = OrchestratorController(plan=plan, executor=executor)
    
    ctrl.run()
    assert ctrl.context.orchestrator_state == OrchestratorState.FAILED
    assert "1" in ctrl.context.failed_steps
    assert executor.call_counts["1"] == 1


def test_unknown_failure() -> None:
    step1 = TaskStep(step_id="1", title="title", description="desc")
    plan = TaskPlan(goal="Goal", steps=[step1])
    
    executor = MockExecutor({
        "1": [] # Returns None analysis
    })
    ctrl = OrchestratorController(plan=plan, executor=executor)
    
    ctrl.run()
    assert ctrl.context.orchestrator_state == OrchestratorState.FAILED
    assert "1" in ctrl.context.failed_steps


def test_cancellation() -> None:
    step1 = TaskStep(step_id="1", title="title", description="desc")
    plan = TaskPlan(goal="Goal", steps=[step1])
    ctrl = OrchestratorController(plan=plan, executor=MockExecutor({}))
    
    ctrl.cancel()
    ctrl.run() # Should do nothing
    assert ctrl.context.orchestrator_state == OrchestratorState.CANCELLED
    
def test_dependency_blocking() -> None:
    step1 = TaskStep(step_id="1", title="title", description="desc")
    step2 = TaskStep(step_id="2", title="title", description="desc", dependencies=["1"])
    plan = TaskPlan(goal="Goal", steps=[step1, step2])
    
    executor = MockExecutor({
        "1": [create_mock_analysis(ResultClassification.SECURITY_BLOCKED)],
        "2": [create_mock_analysis(ResultClassification.SUCCESS)]
    })
    ctrl = OrchestratorController(plan=plan, executor=executor)
    
    ctrl.run()
    assert ctrl.context.orchestrator_state == OrchestratorState.BLOCKED
    assert "1" in ctrl.context.blocked_steps
    assert "2" not in ctrl.context.completed_steps
    assert executor.call_counts.get("2", 0) == 0


def test_capability_unavailable() -> None:
    step1 = TaskStep(step_id="1", title="title", description="desc", required_capabilities=["java"])
    plan = TaskPlan(goal="Goal", steps=[step1])
    
    # We pass None for runtime_manager, so 'java' won't be available
    ctrl = OrchestratorController(plan=plan, executor=MockExecutor({}))
    ctrl.run()
    
    assert ctrl.context.orchestrator_state == OrchestratorState.BLOCKED
    assert "1" in ctrl.context.blocked_steps


def test_bounded_history() -> None:
    from velix_agent.orchestrator.models import ExecutionLimits
    step1 = TaskStep(step_id="1", title="title", description="desc")
    plan = TaskPlan(goal="Goal", steps=[step1])
    
    # Give it 60 retryable failures
    results = [create_mock_analysis(ResultClassification.RETRYABLE_FAILURE) for _ in range(60)]
    results.append(create_mock_analysis(ResultClassification.SUCCESS))
    executor = MockExecutor({"1": results})
    
    limits = ExecutionLimits(max_total_attempts=100)
    ctrl = OrchestratorController(plan=plan, executor=executor, max_step_retries=100, limits=limits)
    ctrl.run()
    
    # History should be bounded to 50
    assert len(ctrl.context.execution_history) == 50
