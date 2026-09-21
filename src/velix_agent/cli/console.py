"""Shared Rich console and rendering helpers.

All terminal output should go through these helpers so that styling,
error formatting, and debug output remain consistent across the
application.  Only one Console instance is ever needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

if TYPE_CHECKING:
    from velix_agent.core.response import AgentResponse

# Module-level default console (used when no Runtime is available yet).
_default_console = Console()


def get_console() -> Console:
    """Return the module-level default console."""
    return _default_console


def print_markdown(console: Console, text: str) -> None:
    """Render *text* as Markdown."""
    console.print(Markdown(text))


def print_error(console: Console, message: str) -> None:
    """Print a styled error message."""
    console.print(Text(f"Error: {message}", style="bold red"))


def print_warning(console: Console, message: str) -> None:
    """Print a styled warning message."""
    console.print(Text(f"Warning: {message}", style="bold yellow"))


def print_info(console: Console, message: str) -> None:
    """Print an informational message."""
    console.print(Text(message, style="cyan"))


def print_success(console: Console, message: str) -> None:
    """Print a success message."""
    console.print(Text(message, style="bold green"))


def print_debug(console: Console, message: str) -> None:
    """Print a debug message (dim styling)."""
    console.print(Text(f"[debug] {message}", style="dim"))


def print_task_placeholder(console: Console, task: str) -> None:
    """Display the Phase 1 placeholder for a received task."""
    console.print()
    console.print(
        Panel(
            Text.assemble(
                ("Task received:\n\n", "bold"),
                (f"  {task}\n\n", "cyan"),
                (
                    "VelixAgent AI execution is not available yet.\n"
                    "This functionality will be introduced in a future phase.",
                    "dim",
                ),
            ),
            title="VelixAgent",
            border_style="blue",
            padding=(1, 2),
        )
    )
    console.print()


def print_agent_response(console: Console, response: AgentResponse) -> None:
    """Display an AgentResponse in the CLI."""
    console.print()

    if response.metadata and "fallback_warning" in response.metadata:
        console.print(Text(response.metadata["fallback_warning"], style="bold yellow"))
        console.print()

    if response.status == "error":
        if response.text.startswith("All configured providers are currently unavailable:"):
            console.print("Agent Error", style="bold red")
            console.print()
            console.print(Text(response.text, style="red"))
        else:
            console.print(
                Panel(
                    Text(response.text, style="red"),
                    title="[bold red]Agent Error[/bold red]",
                    title_align="left",
                    border_style="red",
                    padding=(1, 2),
                )
            )
    else:
        # Success response
        # Render markdown content inside a panel
        console.print(
            Panel(
                Markdown(response.text),
                title="Velix",
                title_align="left",
                border_style="cyan",
                padding=(1, 2),
            )
        )
    console.print()
