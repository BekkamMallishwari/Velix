"""Top-level autonomous application loop."""

from velix_agent.core.agent import Agent
from velix_agent.core.coding_agent import CodingAgent
from velix_agent.core.logging import get_logger
from velix_agent.orchestrator.controller import OrchestratorController
from velix_agent.orchestrator.models import OrchestratorState
from velix_agent.planning.planner import TaskPlanner

logger = get_logger("application")


class AutonomousCodingLoop:
    """The main application entrypoint connecting planner, orchestrator, and execution."""

    def __init__(
        self,
        agent: Agent,
        planner: TaskPlanner,
    ) -> None:
        self.agent = agent
        self.planner = planner

    def run(self, user_request: str) -> OrchestratorState:
        """Run the autonomous loop for the given request."""
        logger.info("Starting autonomous loop for request.")

        # 1. Create a plan
        try:
            plan = self.planner.create_plan(user_request)
        except Exception as e:
            logger.error("Planning failed: %s", e)
            return OrchestratorState.FAILED

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
        if getattr(self.agent.config, "use_shadow_workspace", False):
            from velix_agent.tools.registry import create_default_tool_registry
            from velix_agent.workspace.session import ShadowWorkspaceSession

            with ShadowWorkspaceSession(
                host_workspace=self.agent.cwd,
                max_files=self.agent.config.shadow_max_files,
                max_bytes=self.agent.config.shadow_max_bytes,
            ) as shadow_root:
                logger.info("Shadow workspace active at: %s", shadow_root)
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
                    controller.run()
                finally:
                    self.agent.tool_registry = saved_registry
                    self.agent.cwd = saved_cwd
        else:
            controller.run()

        logger.info("Orchestrator finished with state: %s", controller.context.orchestrator_state)
        return controller.context.orchestrator_state

