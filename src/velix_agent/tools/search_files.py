"""Tool for searching file contents within the workspace."""

import re
from pathlib import Path
from typing import Any

from velix_agent.tools.base import Tool, ToolResult
from velix_agent.utils.paths import resolve_safe_path

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB limit per file
MAX_MATCHES = 100
MAX_SCANNED_FILES = 10000
MAX_REGEX_LINE_LENGTH = 2000  # Mitigation for ReDoS: bound line length for regex evaluation

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
}


class SearchFilesTool(Tool):
    """Tool for searching file contents within the allowed workspace."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        if not self.workspace_root.is_dir():
            raise ValueError(f"Invalid workspace root: {self.workspace_root}")

    @property
    def name(self) -> str:
        return "search_files"

    @property
    def description(self) -> str:
        return (
            "Search file contents for a query and return matching file paths, "
            "line numbers, and matching lines."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The string or regular expression to search for.",
                },
                "directory": {
                    "type": "string",
                    "description": (
                        "Optional relative path to a directory within the "
                        "workspace to narrow the search."
                    ),
                },
                "is_regex": {
                    "type": "boolean",
                    "description": (
                        "Whether to treat the query as a regular expression. Defaults to false."
                    ),
                },
                "file_pattern": {
                    "type": "string",
                    "description": (
                        "Optional glob pattern to restrict searched files (e.g. '*.py')."
                    ),
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": (
                        "Whether the search should be case-insensitive. Defaults to false."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Optional maximum number of results to return.",
                },
                "regex": {
                    "type": "boolean",
                    "description": "Alias for is_regex.",
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query")
        if query is None:
            return ToolResult(status="error", error="Missing required argument: 'query'")
        if not isinstance(query, str):
            return ToolResult(status="error", error="Argument 'query' must be a string.")
        if not query:
            return ToolResult(status="error", error="Argument 'query' cannot be empty.")

        directory_str = kwargs.get("directory")
        if directory_str is not None and not isinstance(directory_str, str):
            return ToolResult(status="error", error="Argument 'directory' must be a string.")
        directory_str = directory_str or ""

        file_pattern = kwargs.get("file_pattern")
        if file_pattern is not None and not isinstance(file_pattern, str):
            return ToolResult(status="error", error="Argument 'file_pattern' must be a string.")
        file_pattern = file_pattern or "*"

        is_regex_val = kwargs.get("is_regex")
        if is_regex_val is not None and type(is_regex_val) is not bool:
            return ToolResult(status="error", error="Argument 'is_regex' must be a boolean.")

        regex_val = kwargs.get("regex")
        if regex_val is not None and type(regex_val) is not bool:
            return ToolResult(status="error", error="Argument 'regex' must be a boolean.")

        is_regex = bool(is_regex_val or regex_val)

        ignore_case = kwargs.get("ignore_case")
        if ignore_case is not None and type(ignore_case) is not bool:
            return ToolResult(status="error", error="Argument 'ignore_case' must be a boolean.")
        ignore_case = bool(ignore_case)

        max_results = kwargs.get("max_results")
        if max_results is not None:
            if type(max_results) is bool or not isinstance(max_results, int):
                return ToolResult(
                    status="error", error="Argument 'max_results' must be an integer."
                )
            if max_results <= 0:
                return ToolResult(status="error", error="Argument 'max_results' must be positive.")
        else:
            max_results = MAX_MATCHES

        try:
            target_dir = resolve_safe_path(self.workspace_root, directory_str)
            if not target_dir.is_dir():
                return ToolResult(
                    status="error", error=f"Path is not a valid directory: {directory_str}"
                )
        except PermissionError as e:
            msg = str(e)
            if "Access denied" in msg:
                return ToolResult(status="error", error=msg)
            return ToolResult(
                status="error", error=f"Permission denied accessing directory: {directory_str}"
            )

        flags = re.IGNORECASE if ignore_case else 0
        pattern = None
        if is_regex:
            try:
                pattern = re.compile(query, flags)
            except re.error as e:
                return ToolResult(status="error", error=f"Invalid regular expression: {e}")
        else:
            if ignore_case:
                query = query.lower()

        matches = []
        scanned_count = 0
        truncated = False

        stack = [target_dir]
        visited = set()

        while stack and scanned_count < MAX_SCANNED_FILES:
            current_dir = stack.pop()

            try:
                resolved_dir = current_dir.resolve()
            except OSError:
                continue

            if resolved_dir in visited:
                continue
            visited.add(resolved_dir)

            try:
                entries = list(current_dir.iterdir())
            except OSError:
                continue

            for entry in entries:
                if entry.name in EXCLUDED_DIRS:
                    continue

                if entry.is_dir():
                    try:
                        resolved_entry = entry.resolve()
                        if resolved_entry.is_relative_to(self.workspace_root) and (
                            resolved_entry not in visited
                        ):
                            stack.append(entry)
                    except OSError:
                        pass
                elif entry.is_file() and entry.match(file_pattern):
                    scanned_count += 1
                    if scanned_count > MAX_SCANNED_FILES:
                        truncated = True
                        break

                    try:
                        resolved_file = entry.resolve()
                        if not resolved_file.is_relative_to(self.workspace_root):
                            continue

                        if resolved_file.stat().st_size > MAX_FILE_SIZE:
                            continue

                        content = resolved_file.read_text(encoding="utf-8")

                        for i, line in enumerate(content.splitlines(), start=1):
                            if pattern:
                                # Mitigation: bound line length for regex to prevent ReDoS hanging.
                                # Limits input size mathematically instead of hard timeouts.
                                matched = bool(pattern.search(line[:MAX_REGEX_LINE_LENGTH]))
                            else:
                                matched = query in line.lower() if ignore_case else query in line

                            if matched:
                                rel_path = str(entry.relative_to(self.workspace_root))
                                rel_path = rel_path.replace("\\", "/")
                                matches.append(
                                    {"file": rel_path, "line_number": i, "content": line.strip()}
                                )
                                if len(matches) >= max_results:
                                    truncated = True
                                    break
                        if truncated:
                            break
                    except (OSError, UnicodeDecodeError):
                        continue
            if truncated:
                break

        return ToolResult(
            status="success",
            data={"matches": matches, "total_matches": len(matches), "truncated": truncated},
        )
