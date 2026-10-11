"""VelixAgent Typer CLI application.

This module defines the top-level ``velix`` command, including:
  - ``--version`` flag
  - ``--debug`` flag
  - One-shot task mode (``velix "some task"``)
  - Interactive REPL (``velix`` with no arguments)
  - ``velix config`` subcommand

Architecture note:
  Typer does not easily support a top-level positional argument alongside
  subcommands (it tries to match positional text as subcommand names).
  We solve this by using a single Typer command with no subcommands,
  and routing ``config`` manually based on the task argument value.
  This gives us clean support for both ``velix config`` and
  ``velix "fix the tests"`` simultaneously.
"""

from __future__ import annotations

import time
from typing import Annotated

import typer

from velix_agent import __version__
from velix_agent.cli.console import get_console, print_error
from velix_agent.core.errors import VelixError
from velix_agent.core.logging import get_logger

logger = get_logger("cli")

# ---------------------------------------------------------------------------
# Help epilog — rendered by Typer/Rich in the --help output
# ---------------------------------------------------------------------------

_EPILOG = """
[bold]Examples:[/bold]

  [cyan]velix "fix the failing tests"[/cyan]     Run a one-shot task
  [cyan]velix[/cyan]                              Start interactive REPL
  [cyan]velix config[/cyan]                       Show current configuration
  [cyan]velix -d "add logging"[/cyan]             One-shot with debug output

[bold]Environment variables:[/bold]

  [dim]VELIX_DEFAULT_PROVIDER[/dim]         Provider to use (gemini, openai, anthropic, local)
  [dim]VELIX_DEFAULT_MODEL[/dim]            Model name (e.g. gemini-3.6-flash)
  [dim]GEMINI_API_KEY[/dim]                 API key for Gemini provider
  [dim]OPENAI_API_KEY[/dim]                 API key for OpenAI provider
  [dim]ANTHROPIC_API_KEY[/dim]              API key for Anthropic provider
  [dim]VELIX_USE_SHADOW_WORKSPACE[/dim]     Enable shadow workspace isolation (true/false)
  [dim]VELIX_SHADOW_MAX_FILES[/dim]         Max files to seed (default 10 000)
  [dim]VELIX_SHADOW_MAX_BYTES[/dim]         Max bytes to seed (default 2 GB)
  [dim]VELIX_DEBUG[/dim]                    Enable debug mode (true/false)
"""

# ---------------------------------------------------------------------------
# Typer application
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="velix",
    help="VelixAgent — A powerful multimodal AI coding agent.",
    no_args_is_help=False,
    add_completion=False,
    rich_markup_mode="rich",
    epilog=_EPILOG,
)


# ---------------------------------------------------------------------------
# Version callback
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"VelixAgent v{__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Spinner helper
# ---------------------------------------------------------------------------

_PHASE_ICONS: dict[str, str] = {
    "planning": "🔍",
    "planned": "📋",
    "shadow": "🔒",
    "step": "⚡",
    "retry": "🔄",
    "done": "✅",
    "error": "❌",
}


def _format_status(phase: str, detail: str, elapsed: float) -> str:
    """Build a spinner status string with an icon and elapsed time."""
    icon = _PHASE_ICONS.get(phase, "⏳")
    mins, secs = divmod(int(elapsed), 60)
    time_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
    return f"{icon} {detail}  [dim]({time_str})[/dim]"


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------


@app.command(epilog=_EPILOG)
def main(
    task: Annotated[
        str | None,
        typer.Argument(help="A coding task to execute, or 'config' to show configuration."),
    ] = None,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show the application version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", "-d", help="Enable debug mode."),
    ] = False,
    one_shot: Annotated[
        bool,
        typer.Option(
            "--one-shot",
            help="Explicit one-shot mode flag (optional when providing a task argument).",
        ),
    ] = False,
) -> None:
    """VelixAgent — A powerful multimodal AI coding agent.

    Run with a TASK argument for one-shot mode, or without arguments
    to start the interactive REPL.  Use ``velix config`` to display
    the current configuration.
    """
    from velix_agent.core.runtime import Runtime

    console = get_console()

    try:
        runtime = Runtime.create(debug=debug, console=console)

        if task == "config":
            from velix_agent.cli.commands import handle_config

            handle_config(runtime)
        elif task is not None:
            # One-shot mode.
            logger.debug("One-shot task: %s", task)
            _run_one_shot(runtime, task)
        else:
            # Interactive REPL.
            from velix_agent.cli.repl import start_repl

            start_repl(runtime)
    except VelixError as exc:
        if debug:
            raise
        print_error(console, exc.message)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        raise typer.Exit() from None
    except typer.Exit:
        raise
    except Exception as exc:
        if debug:
            raise
        print_error(console, f"Unexpected error: {exc}")
        raise typer.Exit(code=1) from exc


def _run_one_shot(runtime: "Runtime", task: str) -> None:
    """Execute a one-shot task with a live progress spinner."""
    from rich.status import Status

    from velix_agent.orchestrator.models import OrchestratorState

    console = runtime.console
    start = time.monotonic()

    # Rich Status spinner — updated by the progress callback.
    status = Status(
        "Initializing…",
        console=console,
        spinner="dots",
        spinner_style="cyan",
    )

    def _on_progress(phase: str, detail: str) -> None:
        elapsed = time.monotonic() - start
        status.update(_format_status(phase, detail, elapsed))

    status.start()
    try:
        state = runtime.app_loop.run(task, on_progress=_on_progress)
    finally:
        status.stop()

    elapsed = time.monotonic() - start
    mins, secs = divmod(int(elapsed), 60)
    time_str = f"{mins}m {secs}s" if mins else f"{secs}s"

    if state == OrchestratorState.COMPLETED:
        console.print(f"\n[green]✅ Task completed successfully.[/green]  [dim]({time_str})[/dim]")
    elif state == OrchestratorState.FAILED:
        print_error(console, f"Task failed.  ({time_str})")
        raise typer.Exit(code=1)
    elif state == OrchestratorState.BLOCKED:
        print_error(console, f"Task blocked due to missing capabilities.  ({time_str})")
        raise typer.Exit(code=1)
    elif state == OrchestratorState.CANCELLED:
        console.print(f"\n[yellow]Task cancelled.[/yellow]  [dim]({time_str})[/dim]")
        raise typer.Exit(code=1)
    else:
        console.print(f"\nTask finished with state: {state}  [dim]({time_str})[/dim]")

