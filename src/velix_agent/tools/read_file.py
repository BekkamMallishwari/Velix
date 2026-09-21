"""Tool for reading file contents safely."""

from pathlib import Path
from typing import Any

from velix_agent.tools.base import Tool, ToolResult


class ReadFileTool(Tool):
    """Tool for reading files within the allowed workspace."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        if not self.workspace_root.is_dir():
            raise ValueError(f"Invalid workspace root: {self.workspace_root}")

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Reads the contents of a file within the allowed workspace."

    def execute(self, **kwargs: Any) -> ToolResult:
        file_path_str = kwargs.get("file_path")
        if not file_path_str:
            return ToolResult(
                status="error", error="Missing required argument: 'file_path'"
            )

        try:
            # We assume file_path could be absolute or relative to workspace root
            target_path = Path(file_path_str)
            if not target_path.is_absolute():
                target_path = self.workspace_root / target_path

            target_path = target_path.resolve()

            # Prevent traversal outside workspace
            if not target_path.is_relative_to(self.workspace_root):
                return ToolResult(
                    status="error",
                    error=f"Access denied: {file_path_str} is outside the allowed workspace.",
                )

            if not target_path.exists():
                return ToolResult(
                    status="error", error=f"File not found: {file_path_str}"
                )

            if target_path.is_dir():
                return ToolResult(
                    status="error", error=f"Path is a directory, not a file: {file_path_str}"
                )

            # Read file contents
            content = target_path.read_text(encoding="utf-8")
            return ToolResult(status="success", data={"content": content})

        except PermissionError:
            return ToolResult(
                status="error", error=f"Permission denied reading file: {file_path_str}"
            )
        except UnicodeDecodeError:
            return ToolResult(
                status="error", error=f"File is not valid UTF-8 text: {file_path_str}"
            )
        except Exception as e:
            return ToolResult(
                status="error", error=f"Unexpected error reading file: {e!s}"
            )
