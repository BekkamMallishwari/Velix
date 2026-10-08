from typing import Any

from velix_agent.memory.store import MemoryError, MemoryManager
from velix_agent.tools.base import Tool, ToolResult


class SearchMemoryTool(Tool):
    """Tool for searching memory from SQLite."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self.memory_manager = memory_manager

    @property
    def name(self) -> str:
        return "search_memory"

    @property
    def description(self) -> str:
        return "Search the local SQLite memory for relevant project facts or hindsight."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 5, max 10).",
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query")
        limit = kwargs.get("limit", 5)

        if not query or not isinstance(query, str) or not query.strip():
            return ToolResult(status="error", error="Missing or empty required argument: 'query'.")

        if not isinstance(limit, int):
            return ToolResult(status="error", error="Argument 'limit' must be an integer.")

        try:
            results = self.memory_manager.search(query, limit)
            return ToolResult(status="success", data={"results": results})
        except MemoryError as e:
            return ToolResult(status="error", error=f"Memory search failed: {e!s}")
        except Exception as e:
            return ToolResult(status="error", error=f"Unexpected error: {e!s}")
