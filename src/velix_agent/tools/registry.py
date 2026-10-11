from pathlib import Path
from typing import Any

from velix_agent.tools.base import Tool


class ToolRegistry:
    """Manages available tools for the agent."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a new tool.

        Raises:
            ValueError: If a tool with the same name is already registered.
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Tool | None:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())


def create_default_tool_registry(
    workspace_root: str | Path,
    sandbox_manager: Any = None,
    memory_store: Any = None,
) -> ToolRegistry:
    """Create a standard ToolRegistry bound to the specified workspace_root.

    Binds file tools and command execution directly to the given workspace root,
    which may be either the primary host workspace or an isolated shadow workspace.
    """
    from velix_agent.tools.delete_memory import DeleteMemoryTool
    from velix_agent.tools.edit_file import EditFileTool
    from velix_agent.tools.list_directory import ListDirectoryTool
    from velix_agent.tools.read_file import ReadFileTool
    from velix_agent.tools.run_command import RunCommandTool
    from velix_agent.tools.search_files import SearchFilesTool
    from velix_agent.tools.search_memory import SearchMemoryTool
    from velix_agent.tools.store_memory import StoreMemoryTool
    from velix_agent.tools.write_file import WriteFileTool

    root = Path(workspace_root).resolve()
    registry = ToolRegistry()
    registry.register(ReadFileTool(root))
    registry.register(WriteFileTool(root))
    registry.register(EditFileTool(root))
    registry.register(ListDirectoryTool(root))
    registry.register(SearchFilesTool(root))

    if sandbox_manager is not None:
        registry.register(RunCommandTool(sandbox_manager, root))

    if memory_store is not None:
        registry.register(StoreMemoryTool(memory_store))
        registry.register(SearchMemoryTool(memory_store))
        registry.register(DeleteMemoryTool(memory_store))

    return registry

