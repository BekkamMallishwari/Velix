"""Interactive REPL for VelixAgent.

Uses ``prompt_toolkit`` for line editing, history, and keybinding support.
History is persisted via platformdirs so it survives between sessions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory, InMemoryHistory
from rich.panel import Panel
from rich.text import Text

from velix_agent import __version__
from velix_agent.cli.commands import dispatch
from velix_agent.cli.console import print_error, print_info
from velix_agent.core.logging import get_logger
from velix_agent.utils.paths import ensure_parent_exists

if TYPE_CHECKING:
    from prompt_toolkit.history import History

    from velix_agent.core.runtime import Runtime

logger = get_logger("repl")


def _build_history(runtime: Runtime) -> History:
    """Select the appropriate prompt_toolkit history backend."""
    if runtime.config.history_enabled:
        history_path = ensure_parent_exists(runtime.config.history_file)
        logger.debug("REPL history file: %s", history_path)
        return FileHistory(str(history_path))
    return InMemoryHistory()


def _print_banner(runtime: Runtime) -> None:
    """Print a concise welcome banner."""
    runtime.console.print(
        Panel(
            Text.assemble(
                ("              VELIXAGENT\n", "bold cyan"),
                (f"          AI Coding Agent v{__version__}", "cyan"),
            ),
            border_style="cyan",
            padding=(1, 2),
        )
    )
    runtime.console.print("[dim]Type your request or `/help`.[/dim]\n")


def start_repl(runtime: Runtime) -> None:
    """Launch the interactive REPL loop.

    Handles Ctrl+C (cancel current input), Ctrl+D / EOF (clean exit),
    empty/whitespace input (ignored), slash commands, and plain text
    tasks (routed to Agent Core).
    """
    from velix_agent.cli.console import print_agent_response

    _print_banner(runtime)

    session: PromptSession[str] = PromptSession(
        history=_build_history(runtime),
    )

    while True:
        try:
            # Display "You: " similar to Phase 2 spec
            user_input = session.prompt("You: ")
        except KeyboardInterrupt:
            # Ctrl+C — cancel current input, continue loop.
            runtime.console.print()
            continue
        except EOFError:
            # Ctrl+D / EOF — clean exit.
            print_info(runtime.console, "\nGoodbye!")
            break

        stripped = user_input.strip()
        if not stripped:
            continue

        # Try slash-command dispatch first.
        result = dispatch(runtime, stripped)
        if result is False:
            # Command signalled exit.
            break
        if result is True:
            # Command handled; wait for next input.
            continue

        # Not a slash command — treat as a coding task.
        logger.debug("Task received: %s", stripped)
        try:
            response = runtime.agent.respond(stripped)
            print_agent_response(runtime.console, response)
        except Exception:
            print_error(runtime.console, "Failed to process task.")
            logger.exception("Unexpected error handling task")
