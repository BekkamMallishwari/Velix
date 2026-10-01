"""Tool for securely executing shell commands within the sandbox."""

from pathlib import Path
from typing import Any

from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.result import SandboxError
from velix_agent.tools.base import Tool, ToolResult


class RunCommandTool(Tool):
    """Executes a command safely within the sandbox."""

    def __init__(self, sandbox: SandboxManager, workspace_root: Path | str) -> None:
        self.sandbox = sandbox
        self.workspace_root = Path(workspace_root).resolve()
        if not self.workspace_root.is_dir():
            raise ValueError(f"Invalid workspace root: {self.workspace_root}")

    @property
    def name(self) -> str:
        return "run_command"

    @property
    def description(self) -> str:
        return "Executes a shell command safely within the configured sandbox."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "The command and its arguments as a list of strings, e.g. ['ls', '-la']."
                    ),
                },
            },
            "required": ["command"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command")
        if not command:
            return ToolResult(status="error", error="Missing required argument: 'command'")
        if not isinstance(command, list):
            return ToolResult(
                status="error",
                error="'command' must be a list of strings (e.g. ['ls', '-la']).",
            )

        try:
            # We strictly pass the command to the sandbox manager
            result = self.sandbox.execute(command=command, workspace_root=self.workspace_root)

            return ToolResult(
                status="success",
                data={
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "success": result.exit_code == 0,
                },
            )
        except SandboxError as e:
            return ToolResult(status="error", error=f"Sandbox rejected execution: {e!s}")
        except Exception as e:
            return ToolResult(status="error", error=f"Unexpected error executing command: {e!s}")
