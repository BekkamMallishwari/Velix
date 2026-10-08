from typing import Any

from velix_agent.memory.store import MemoryError, MemoryManager
from velix_agent.tools.base import Tool, ToolResult


class DeleteMemoryTool(Tool):
    """Tool for deleting a memory entry."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self.memory_manager = memory_manager

    @property
    def name(self) -> str:
        return "delete_memory"

    @property
    def description(self) -> str:
        return "Delete a specific memory entry by ID from the local SQLite memory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "integer",
                    "description": "ID of the memory to delete.",
                },
            },
            "required": ["memory_id"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        memory_id = kwargs.get("memory_id")

        if memory_id is None or not isinstance(memory_id, int):
            return ToolResult(
                status="error", error="Missing or invalid required argument: 'memory_id'."
            )

        try:
            deleted = self.memory_manager.delete(memory_id)
            if deleted:
                return ToolResult(status="success", data={"deleted": True})
            else:
                return ToolResult(status="error", error=f"Memory ID {memory_id} not found.")
        except MemoryError as e:
            return ToolResult(status="error", error=f"Memory deletion failed: {e!s}")
        except Exception as e:
            return ToolResult(status="error", error=f"Unexpected error: {e!s}")
