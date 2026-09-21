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

from typing import Annotated

import typer

from velix_agent import __version__
from velix_agent.cli.console import get_console, print_error
from velix_agent.core.errors import VelixError
from velix_agent.core.logging import get_logger

logger = get_logger("cli")

# ---------------------------------------------------------------------------
# Typer application
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="velix",
    help="VelixAgent — A powerful multimodal AI coding agent.",
    no_args_is_help=False,
    add_completion=False,
    rich_markup_mode="rich",
)


# ---------------------------------------------------------------------------
# Version callback
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"VelixAgent v{__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------


@app.command()
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
            from velix_agent.cli.console import print_agent_response

            response = runtime.agent.respond(task)
            print_agent_response(runtime.console, response)
        else:
            # Interactive REPL.
            from velix_agent.cli.repl import start_repl

            start_repl(runtime)
    except VelixError as exc:
        print_error(console, exc.message)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        raise typer.Exit() from None
    except Exception as exc:
        if debug:
            raise
        print_error(console, f"Unexpected error: {exc}")
        raise typer.Exit(code=1) from exc
