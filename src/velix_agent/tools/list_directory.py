"""Tool for listing directory contents safely."""

from pathlib import Path
from typing import Any

from velix_agent.tools.base import Tool, ToolResult


class ListDirectoryTool(Tool):
    """Tool for listing directory contents within the allowed workspace."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        if not self.workspace_root.is_dir():
            raise ValueError(f"Invalid workspace root: {self.workspace_root}")

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return "Lists files and directories within a specified path in the workspace."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "dir_path": {
                    "type": "string",
                    "description": (
                        "Relative or absolute path to the directory to list "
                        "within the workspace. Use '.' for the workspace root."
                    ),
                },
            },
            "required": ["dir_path"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        dir_path_str = kwargs.get("dir_path")
        if not dir_path_str:
            return ToolResult(status="error", error="Missing required argument: 'dir_path'")
        if not isinstance(dir_path_str, str):
            return ToolResult(status="error", error="Argument 'dir_path' must be a string.")

        try:
            from velix_agent.utils.paths import resolve_safe_path

            target_path = resolve_safe_path(self.workspace_root, dir_path_str)

            if not target_path.exists():
                return ToolResult(status="error", error=f"Directory not found: {dir_path_str}")

            if not target_path.is_dir():
                return ToolResult(
                    status="error", error=f"Path is a file, not a directory: {dir_path_str}"
                )

            items = []
            for item in target_path.iterdir():
                items.append(
                    {
                        "name": item.name,
                        "type": "directory" if item.is_dir() else "file",
                    }
                )

            # Sort items by name for consistent output
            items.sort(key=lambda x: x["name"])

            return ToolResult(status="success", data={"items": items})

        except PermissionError as e:
            msg = str(e)
            if "Access denied" in msg:
                return ToolResult(status="error", error=msg)
            return ToolResult(
                status="error", error=f"Permission denied listing directory: {dir_path_str}"
            )
        except Exception as e:
            return ToolResult(status="error", error=f"Unexpected error listing directory: {e!s}")
