"""Tool for creating or overwriting file contents safely."""

from pathlib import Path
from typing import Any

from velix_agent.tools.base import Tool, ToolResult


class WriteFileTool(Tool):
    """Tool for writing files securely within the allowed workspace."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        if not self.workspace_root.is_dir():
            raise ValueError(f"Invalid workspace root: {self.workspace_root}")

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Creates a new file or overwrites an existing file with the provided content within the allowed workspace."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative or absolute path to the file to write within the workspace.",
                },
                "content": {
                    "type": "string",
                    "description": "The full text content to write to the file.",
                },
            },
            "required": ["file_path", "content"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        file_path_str = kwargs.get("file_path")
        content = kwargs.get("content")

        if not file_path_str:
            return ToolResult(
                status="error", error="Missing required argument: 'file_path'"
            )
        if content is None:
            return ToolResult(
                status="error", error="Missing required argument: 'content'"
            )
        if not isinstance(content, str):
            return ToolResult(
                status="error", error="Argument 'content' must be a string."
            )

        try:
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

            # Prevent writing to or inside .git
            if ".git" in target_path.parts:
                return ToolResult(
                    status="error",
                    error="Access denied: Cannot write to protected .git paths.",
                )

            if target_path.exists() and target_path.is_dir():
                return ToolResult(
                    status="error", error=f"Path is a directory, not a file: {file_path_str}"
                )

            # Create parent directories if they don't exist
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file contents
            target_path.write_text(content, encoding="utf-8")
            return ToolResult(
                status="success",
                data={"message": f"Successfully wrote to {file_path_str}", "size": len(content)}
            )

        except PermissionError:
            return ToolResult(
                status="error", error=f"Permission denied writing file: {file_path_str}"
            )
        except Exception as e:
            return ToolResult(
                status="error", error=f"Unexpected error writing file: {e!s}"
            )
