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

    def execute(self, **kwargs: Any) -> ToolResult:
        dir_path_str = kwargs.get("dir_path")
        if not dir_path_str:
            return ToolResult(
                status="error", error="Missing required argument: 'dir_path'"
            )

        try:
            target_path = Path(dir_path_str)
            if not target_path.is_absolute():
                target_path = self.workspace_root / target_path

            target_path = target_path.resolve()

            # Prevent traversal outside workspace
            if not target_path.is_relative_to(self.workspace_root):
                return ToolResult(
                    status="error",
                    error=f"Access denied: {dir_path_str} is outside the allowed workspace.",
                )

            if not target_path.exists():
                return ToolResult(
                    status="error", error=f"Directory not found: {dir_path_str}"
                )

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

        except PermissionError:
            return ToolResult(
                status="error", error=f"Permission denied listing directory: {dir_path_str}"
            )
        except Exception as e:
            return ToolResult(
                status="error", error=f"Unexpected error listing directory: {e!s}"
            )
