"""Tool for editing existing file contents safely."""

from pathlib import Path
from typing import Any

from velix_agent.tools.base import Tool, ToolResult


class EditFileTool(Tool):
    """Tool for securely editing files within the allowed workspace."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        if not self.workspace_root.is_dir():
            raise ValueError(f"Invalid workspace root: {self.workspace_root}")

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edits an existing file by replacing an exact string occurrence with new text."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Relative or absolute path to the file to edit within the workspace."
                    ),
                },
                "old_text": {
                    "type": "string",
                    "description": (
                        "The exact text to find and replace. Must appear exactly once in the file."
                    ),
                },
                "new_text": {
                    "type": "string",
                    "description": "The replacement text.",
                },
            },
            "required": ["file_path", "old_text", "new_text"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        file_path_str = kwargs.get("file_path")
        old_text = kwargs.get("old_text")
        new_text = kwargs.get("new_text")

        if not file_path_str:
            return ToolResult(status="error", error="Missing required argument: 'file_path'")
        if old_text is None:
            return ToolResult(status="error", error="Missing required argument: 'old_text'")
        if new_text is None:
            return ToolResult(status="error", error="Missing required argument: 'new_text'")
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            return ToolResult(status="error", error="'old_text' and 'new_text' must be strings.")

        try:
            from velix_agent.utils.paths import resolve_safe_path

            target_path = resolve_safe_path(self.workspace_root, file_path_str, is_write=True)

            if not target_path.exists():
                return ToolResult(status="error", error=f"File not found: {file_path_str}")

            if target_path.is_dir():
                return ToolResult(
                    status="error", error=f"Path is a directory, not a file: {file_path_str}"
                )

            # Read file contents
            content = target_path.read_text(encoding="utf-8")

            occurrences = content.count(old_text)
            if occurrences == 0:
                return ToolResult(
                    status="error", error="The expected old_text was not found in the file."
                )
            if occurrences > 1:
                return ToolResult(
                    status="error", error="Ambiguous replacement: old_text occurs multiple times."
                )

            new_content = content.replace(old_text, new_text)
            target_path.write_text(new_content, encoding="utf-8")

            return ToolResult(
                status="success", data={"message": f"Successfully edited {file_path_str}"}
            )

        except PermissionError as e:
            msg = str(e)
            if "Access denied" in msg:
                return ToolResult(status="error", error=msg)
            return ToolResult(
                status="error", error=f"Permission denied editing file: {file_path_str}"
            )
        except UnicodeDecodeError:
            return ToolResult(
                status="error", error=f"File is not valid UTF-8 text: {file_path_str}"
            )
        except Exception as e:
            return ToolResult(status="error", error=f"Unexpected error editing file: {e!s}")
