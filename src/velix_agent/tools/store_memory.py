from typing import Any

from velix_agent.memory.store import MemoryError, MemoryManager
from velix_agent.tools.base import Tool, ToolResult


class StoreMemoryTool(Tool):
    """Tool for storing memory into SQLite."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self.memory_manager = memory_manager

    @property
    def name(self) -> str:
        return "store_memory"

    @property
    def description(self) -> str:
        return "Store important project facts or task hindsight into the local SQLite memory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "memory_type": {
                    "type": "string",
                    "description": "Type of memory. Must be 'project_fact' or 'task_hindsight'.",
                },
                "topic": {
                    "type": "string",
                    "description": "Short topic of the memory (max 100 chars).",
                },
                "content": {
                    "type": "string",
                    "description": "Content of the memory (max 2000 chars).",
                },
            },
            "required": ["memory_type", "topic", "content"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        memory_type = kwargs.get("memory_type")
        topic = kwargs.get("topic")
        content = kwargs.get("content")

        if not memory_type or not topic or not content:
            return ToolResult(status="error", error="Missing required arguments.")

        if (
            not isinstance(memory_type, str)
            or not isinstance(topic, str)
            or not isinstance(content, str)
        ):
            return ToolResult(status="error", error="Arguments must be strings.")

        try:
            mem_id = self.memory_manager.store(memory_type, topic, content)
            return ToolResult(status="success", data={"id": mem_id, "status": "stored"})
        except MemoryError as e:
            return ToolResult(status="error", error=f"Memory storage failed: {e!s}")
        except Exception as e:
            return ToolResult(status="error", error=f"Unexpected error: {e!s}")
