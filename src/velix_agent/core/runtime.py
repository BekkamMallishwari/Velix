"""Application runtime for VelixAgent.

The Runtime is the single integration point that holds resolved
application state and shared resources.  The CLI and REPL receive
a Runtime rather than creating their own dependencies.

Phase 1 keeps Runtime intentionally minimal.  Future phases will
attach the model gateway, tool registry, planner, executor, memory
engine, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console

from velix_agent.core.agent import Agent
from velix_agent.core.config import VelixConfig
from velix_agent.core.logging import setup_logging
from velix_agent.core.session import Session


@dataclass(slots=True)
class Runtime:
    """Application-level runtime state."""

    config: VelixConfig
    console: Console = field(default_factory=Console)
    session: Session = field(default_factory=Session.create)
    agent: Agent = field(init=False)

    def __post_init__(self) -> None:
        import os
        from pathlib import Path

        from velix_agent.providers.factory import get_provider
        from velix_agent.sandbox.manager import SandboxManager
        from velix_agent.tools.edit_file import EditFileTool
        from velix_agent.tools.list_directory import ListDirectoryTool
        from velix_agent.tools.read_file import ReadFileTool
        from velix_agent.tools.registry import ToolRegistry
        from velix_agent.tools.run_command import RunCommandTool
        from velix_agent.tools.search_files import SearchFilesTool
        from velix_agent.tools.write_file import WriteFileTool

        provider = get_provider(self.config)

        tool_registry = ToolRegistry()
        workspace_root = Path(os.getcwd()).resolve()

        tool_registry.register(ReadFileTool(workspace_root=workspace_root))
        tool_registry.register(WriteFileTool(workspace_root=workspace_root))
        tool_registry.register(EditFileTool(workspace_root=workspace_root))
        tool_registry.register(ListDirectoryTool(workspace_root=workspace_root))
        tool_registry.register(SearchFilesTool(workspace_root=workspace_root))

        sandbox = SandboxManager()
        tool_registry.register(RunCommandTool(sandbox=sandbox, workspace_root=workspace_root))

        memory_manager = None
        if self.config.enable_memory:
            try:
                from velix_agent.memory.store import MemoryManager
                from velix_agent.tools.delete_memory import DeleteMemoryTool
                from velix_agent.tools.search_memory import SearchMemoryTool
                from velix_agent.tools.store_memory import StoreMemoryTool

                memory_manager = MemoryManager(workspace_root=workspace_root)
                tool_registry.register(StoreMemoryTool(memory_manager=memory_manager))
                tool_registry.register(SearchMemoryTool(memory_manager=memory_manager))
                tool_registry.register(DeleteMemoryTool(memory_manager=memory_manager))
            except Exception as e:
                # Log but do not crash
                import logging

                logging.getLogger("runtime").warning("Failed to initialize memory tools: %s", e)

        self.agent = Agent(
            self.session,
            provider,
            tool_registry=tool_registry,
            config=self.config,
            memory_manager=memory_manager,
        )

    @property
    def debug(self) -> bool:
        """Convenience accessor for debug mode."""
        return self.config.debug

    @classmethod
    def create(
        cls,
        *,
        debug: bool | None = None,
        console: Console | None = None,
    ) -> Runtime:
        """Build a Runtime from environment / defaults with optional CLI overrides.

        Parameters
        ----------
        debug:
            If provided, overrides the ``VELIX_DEBUG`` env / default value.
        console:
            If provided, uses this Rich Console instead of creating one.
        """
        config = VelixConfig()

        # CLI-level overrides take highest precedence.
        if debug is not None:
            config = config.model_copy(update={"debug": debug})
            if debug:
                config = config.model_copy(update={"log_level": "DEBUG"})

        setup_logging(level=config.log_level, debug=config.debug)

        return cls(
            config=config,
            console=console or Console(),
        )
