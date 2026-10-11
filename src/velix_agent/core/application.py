"""Top-level autonomous application loop."""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from velix_agent.core.agent import Agent
from velix_agent.core.coding_agent import CodingAgent
from velix_agent.core.logging import get_logger
from velix_agent.orchestrator.controller import OrchestratorController
from velix_agent.orchestrator.models import OrchestratorState
from velix_agent.planning.planner import TaskPlanner

logger = get_logger("application")

# ---------------------------------------------------------------------------
# Progress callback type
# ---------------------------------------------------------------------------

# The callback receives (phase, detail) where:
#   phase  – a short machine-readable label, e.g. "planning", "step", "done"
#   detail – a human-readable description, e.g. "Analyzing task…"
ProgressCallback = Callable[[str, str], None]


class AutonomousCodingLoop:
    """The main application entrypoint connecting planner, orchestrator, and execution."""

    def __init__(
        self,
        agent: Agent,
        planner: TaskPlanner,
    ) -> None:
        self.agent = agent
        self.planner = planner

    def run(
        self,
        user_request: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> OrchestratorState:
        """Run the autonomous loop for the given request.

        Parameters
        ----------
        user_request:
            The user's coding task.
        on_progress:
            Optional callback fired at each major phase so the CLI
            can update a spinner or progress display.
        """
        def _notify(phase: str, detail: str) -> None:
            if on_progress is not None:
                on_progress(phase, detail)

        logger.info("Starting autonomous loop for request.")

        # 1. Create a plan
        _notify("planning", "Analyzing task…")
        try:
            plan = self.planner.create_plan(user_request)
        except Exception as e:
            logger.error("Planning failed: %s", e)
            _notify("error", f"Planning failed: {e}")
            return OrchestratorState.FAILED

        total_steps = len(plan.steps)
        _notify("planned", f"Created plan with {total_steps} step(s)")

        # 2. Setup Step Executor
        executor = CodingAgent(self.agent)

        # 3. Setup Orchestrator
        from velix_agent.orchestrator.models import ExecutionLimits
        limits = ExecutionLimits(
            max_total_attempts=25,
            max_tool_invocations=50,
            max_time_seconds=900
        )

        controller = OrchestratorController(
            plan=plan,
            executor=executor,
            runtime_manager=self.planner.runtime_manager,
            sandbox_manager=self.planner.sandbox_manager,
            limits=limits,
        )

        # 4. Run loop (with optional shadow workspace isolation)
        logger.info("Starting Orchestrator run.")

        def _step_observer() -> None:
            """Called after each controller.step() to fire progress."""
            ctx = controller.context
            completed = len(ctx.completed_steps)
            current = ctx.current_step_id
            state = ctx.orchestrator_state

            if state == OrchestratorState.EXECUTING and current:
                # Find the step title for a friendlier message
                title = current
                for s in plan.steps:
                    if s.step_id == current:
                        title = s.title
                        break
                _notify("step", f"Step {completed + 1}/{total_steps}: {title}")
            elif state == OrchestratorState.RETRYING and current:
                attempt = ctx.step_attempts.get(current, 1)
                _notify("retry", f"Retrying step (attempt {attempt})…")

        if getattr(self.agent.config, "use_shadow_workspace", False):
            from velix_agent.tools.registry import create_default_tool_registry
            from velix_agent.workspace.session import ShadowWorkspaceSession

            _notify("shadow", "Preparing shadow workspace…")
            with ShadowWorkspaceSession(
                host_workspace=self.agent.cwd,
                max_files=self.agent.config.shadow_max_files,
                max_bytes=self.agent.config.shadow_max_bytes,
            ) as shadow_root:
                logger.info("Shadow workspace active at: %s", shadow_root)
                _notify("shadow", "Shadow workspace ready")
                # Rebind agent tools to the shadow root
                saved_registry = self.agent.tool_registry
                saved_cwd = self.agent.cwd
                try:
                    self.agent.tool_registry = create_default_tool_registry(
                        workspace_root=shadow_root,
                        sandbox_manager=self.planner.sandbox_manager,
                        memory_store=self.agent.memory_manager.store if self.agent.memory_manager else None,
                    )
                    self.agent.cwd = shadow_root
                    self._run_controller(controller, _step_observer)
                finally:
                    self.agent.tool_registry = saved_registry
                    self.agent.cwd = saved_cwd
        else:
            self._run_controller(controller, _step_observer)

        final_state = controller.context.orchestrator_state
        logger.info("Orchestrator finished with state: %s", final_state)
        _notify("done", f"Finished: {final_state}")
        return final_state

    @staticmethod
    def _run_controller(
        controller: OrchestratorController,
        step_observer: Callable[[], None],
    ) -> None:
        """Run the orchestrator loop, calling *step_observer* after each step."""
        while controller.context.orchestrator_state not in (
            OrchestratorState.FAILED,
            OrchestratorState.BLOCKED,
            OrchestratorState.COMPLETED,
            OrchestratorState.CANCELLED,
        ):
            step_observer()
            controller.step()

