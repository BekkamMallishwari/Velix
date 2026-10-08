"""Orchestrator controller layer."""

from typing import Any, Optional, Protocol

from velix_agent.analysis.models import AnalysisResult, ResultClassification
from velix_agent.orchestrator.models import (
    OrchestratorContext,
    OrchestratorState,
    StepExecutionResult,
)
from velix_agent.planning.models import StepStatus, TaskPlan, TaskStep
from velix_agent.runtime.manager import RuntimeManager
from velix_agent.sandbox.manager import SandboxManager


class StepExecutor(Protocol):
    def execute_step(self, step: TaskStep, budget: Optional[Any] = None) -> StepExecutionResult: ...


class OrchestratorController:
    def __init__(
        self,
        plan: TaskPlan,
        executor: StepExecutor,
        runtime_manager: Optional[RuntimeManager] = None,
        sandbox_manager: Optional[SandboxManager] = None,
        max_step_retries: int = 2,
        limits: Optional[Any] = None,
    ) -> None:
        self.plan = plan
        self.executor = executor
        self.runtime_manager = runtime_manager
        self.sandbox_manager = sandbox_manager
        self.max_step_retries = max_step_retries
        self.context = OrchestratorContext(
            plan_id="plan_1", orchestrator_state=OrchestratorState.READY
        )

        if limits is None:
            from velix_agent.orchestrator.models import ExecutionLimits
            limits = ExecutionLimits()
        self.limits = limits

        from velix_agent.core.protections import ExecutionBudget
        self.budget = ExecutionBudget(
            max_tool_invocations=self.limits.max_tool_invocations,
            max_time_seconds=self.limits.max_time_seconds,
        )
        self.context.start_time = self.budget.start_time

    def cancel(self) -> None:
        """Cancel execution of the plan."""
        self.context.orchestrator_state = OrchestratorState.CANCELLED

    def get_next_step(self) -> Optional[TaskStep]:
        """Determine the next step to execute based on dependencies and completion state."""
        if self.context.orchestrator_state in (
            OrchestratorState.FAILED,
            OrchestratorState.BLOCKED,
            OrchestratorState.COMPLETED,
            OrchestratorState.CANCELLED,
        ):
            return None

        completed_set = set(self.context.completed_steps)
        for step in self.plan.steps:
            if step.step_id in completed_set:
                continue
            if (
                step.step_id in self.context.failed_steps
                or step.step_id in self.context.blocked_steps
            ):
                continue

            can_run = True
            for dep in step.dependencies:
                if dep not in completed_set:
                    can_run = False
                    break

            if can_run:
                if self._check_capabilities(step):
                    return step
                else:
                    self._block_step(step)
                    return None
        return None

    def _check_capabilities(self, step: TaskStep) -> bool:
        if not step.required_capabilities:
            return True

        available = set()

        if self.runtime_manager:
            runtimes = self.runtime_manager.detect_all(workspace_root=".")
            for name, info in runtimes.items():
                if info.status.name == "SUPPORTED":
                    available.add(name.lower())

        if self.sandbox_manager:
            caps = self.sandbox_manager.get_capabilities()
            if caps.filesystem_isolation == "SUPPORTED":
                available.add("filesystem_isolation")
            if caps.network_isolation == "SUPPORTED":
                available.add("network_isolation")

        for cap in step.required_capabilities:
            if cap.lower() not in available:
                return False

        return True

    def step(self) -> None:
        """Execute one step of the orchestrator."""
        if self.context.orchestrator_state in (
            OrchestratorState.FAILED,
            OrchestratorState.BLOCKED,
            OrchestratorState.COMPLETED,
            OrchestratorState.CANCELLED,
        ):
            return

        if self.budget.is_time_exceeded():
            self.context.orchestrator_state = OrchestratorState.FAILED
            return

        if self.context.total_step_attempts >= self.limits.max_total_attempts:
            self.context.orchestrator_state = OrchestratorState.FAILED
            return

        next_step = self.get_next_step()
        if not next_step:
            if len(self.context.completed_steps) == len(self.plan.steps):
                self.context.orchestrator_state = OrchestratorState.COMPLETED
            elif len(self.context.failed_steps) > 0:
                self.context.orchestrator_state = OrchestratorState.FAILED
            elif len(self.context.blocked_steps) > 0:
                self.context.orchestrator_state = OrchestratorState.BLOCKED
            else:
                self.context.orchestrator_state = OrchestratorState.FAILED
            return

        self.context.current_step_id = next_step.step_id
        self.context.orchestrator_state = OrchestratorState.EXECUTING
        next_step.status = StepStatus.IN_PROGRESS

        self.context.total_step_attempts += 1
        attempts = self.context.step_attempts.get(next_step.step_id, 0)
        self.context.step_attempts[next_step.step_id] = attempts + 1

        if attempts > 0:
            for res in reversed(self.context.execution_history):
                if res.step_id == next_step.step_id:
                    err = res.error or "Unknown error"
                    reason = res.analysis.reason if res.analysis else "Unknown reason"
                    prev_out = (res.output_context or "")[-1000:]
                    next_step.retry_context = (
                        f"Previous attempt {attempts} failed.\n"
                        f"Failure reason: {reason}\n"
                        f"Error: {err}\n"
                        f"Previous result snippet: {prev_out}\n"
                        "Fix the issue instead of repeating the same failed action."
                    )
                    break

        result = self.executor.execute_step(next_step, budget=self.budget)

        self.context.execution_history.append(result)
        if len(self.context.execution_history) > 50:
            self.context.execution_history.pop(0)

        self.context.orchestrator_state = OrchestratorState.ANALYZING
        self._analyze_result(next_step, result)
        self.context.current_step_id = None

    def run(self) -> None:
        """Run the orchestrator until terminal state."""
        while self.context.orchestrator_state not in (
            OrchestratorState.FAILED,
            OrchestratorState.BLOCKED,
            OrchestratorState.COMPLETED,
            OrchestratorState.CANCELLED,
        ):
            self.step()

    def _analyze_result(self, step: TaskStep, result: StepExecutionResult) -> None:
        self.context.total_tool_calls += getattr(result, "tool_call_count", 0)

        if not result.analysis:
            self._fail_step(step)
            return

        self.context.last_analysis = result.analysis
        cls = result.analysis.classification

        if cls == ResultClassification.SUCCESS:
            self._complete_step(step)
        elif cls in (ResultClassification.SECURITY_BLOCKED, ResultClassification.RESOURCE_LIMIT):
            self._block_step(step)
        elif cls in (ResultClassification.RETRYABLE_FAILURE, ResultClassification.TIMEOUT):
            attempts = self.context.step_attempts.get(step.step_id, 0)
            # attempts includes initial attempt. So attempts <= max_step_retries + 1 (i.e. 1 initial + max retries)
            if attempts <= self.max_step_retries:
                self.context.orchestrator_state = OrchestratorState.RETRYING
                step.status = StepStatus.READY
            else:
                self._fail_step(step)
        else:
            self._fail_step(step)

    def _complete_step(self, step: TaskStep) -> None:
        step.status = StepStatus.COMPLETED
        self.context.completed_steps.append(step.step_id)
        self.context.orchestrator_state = OrchestratorState.READY

    def _block_step(self, step: TaskStep) -> None:
        step.status = StepStatus.BLOCKED
        self.context.blocked_steps.append(step.step_id)
        self.context.orchestrator_state = OrchestratorState.BLOCKED

    def _fail_step(self, step: TaskStep) -> None:
        step.status = StepStatus.FAILED
        self.context.failed_steps.append(step.step_id)
        self.context.orchestrator_state = OrchestratorState.FAILED
