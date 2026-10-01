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

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative or absolute path to the file within the workspace.",
                },
            },
            "required": ["file_path"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        file_path_str = kwargs.get("file_path")
        if not file_path_str:
            return ToolResult(status="error", error="Missing required argument: 'file_path'")

        try:
            from velix_agent.utils.paths import resolve_safe_path

            target_path = resolve_safe_path(self.workspace_root, file_path_str)

            if not target_path.exists():
                return ToolResult(status="error", error=f"File not found: {file_path_str}")

            if target_path.is_dir():
                return ToolResult(
                    status="error", error=f"Path is a directory, not a file: {file_path_str}"
                )

            # Read file contents
            content = target_path.read_text(encoding="utf-8")
            return ToolResult(status="success", data={"content": content})

        except PermissionError as e:
            msg = str(e)
            if "Access denied" in msg:
                return ToolResult(status="error", error=msg)
            return ToolResult(
                status="error", error=f"Permission denied reading file: {file_path_str}"
            )
        except UnicodeDecodeError:
            return ToolResult(
                status="error", error=f"File is not valid UTF-8 text: {file_path_str}"
            )
        except Exception as e:
            return ToolResult(status="error", error=f"Unexpected error reading file: {e!s}")
