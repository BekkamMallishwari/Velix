"""Slash-command dispatch for the interactive REPL.

Each command is a plain function that receives the Runtime and returns
a boolean indicating whether the REPL should continue (True) or exit
(False).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from velix_agent import __version__
from velix_agent.cli.console import print_info, print_warning

if TYPE_CHECKING:
    from velix_agent.core.runtime import Runtime


def handle_help(runtime: Runtime) -> bool:
    """Display available REPL commands."""
    help_text = (
        "[bold]Available commands:[/bold]\n"
        "\n"
        "  [cyan]/help[/cyan]      Show this help message\n"
        "  [cyan]/clear[/cyan]     Clear the screen and conversation context\n"
        "  [cyan]/status[/cyan]    Show agent status and session info\n"
        "  [cyan]/config[/cyan]    Show current configuration\n"
        "  [cyan]/version[/cyan]   Show VelixAgent version\n"
        "  [cyan]/exit[/cyan]      Exit VelixAgent\n"
        "  [cyan]/quit[/cyan]      Exit VelixAgent\n"
        "\n"
        "  Any other text is treated as a coding task."
    )
    runtime.console.print(help_text)
    return True


def handle_run(runtime: Runtime, command_str: str) -> bool:
    """Execute a shell command inside the sandbox."""
    import os
    import shlex

    from velix_agent.sandbox.manager import SandboxManager
    from velix_agent.sandbox.result import SandboxError

    parts = shlex.split(command_str)
    if not parts:
        print_warning(runtime.console, "Usage: /run <command>")
        return True

    try:
        manager = SandboxManager()
        result = manager.execute(parts, workspace_root=os.getcwd())

        runtime.console.print(
            f"[bold cyan]Command exited with code: {result.exit_code}[/bold cyan]"
        )
        if result.stdout:
            runtime.console.print("[dim]STDOUT:[/dim]")
            runtime.console.print(result.stdout)
        if result.stderr:
            runtime.console.print("[dim red]STDERR:[/dim red]")
            runtime.console.print(result.stderr)

    except SandboxError as e:
        runtime.console.print(f"[bold red]Sandbox Error:[/bold red] {e}")

    return True


def handle_clear(runtime: Runtime) -> bool:
    """Clear the terminal screen and conversation context."""
    runtime.console.clear()
    runtime.session.clear_conversation()
    print_info(runtime.console, "Conversation context cleared.")
    return True


def handle_status(runtime: Runtime) -> bool:
    """Show agent status and session info."""
    provider = runtime.config.default_provider

    configured = []
    if getattr(runtime.config, "gemini_api_key", None):
        configured.append("Gemini")
    if getattr(runtime.config, "openai_api_key", None):
        configured.append("OpenAI")
    if getattr(runtime.config, "anthropic_api_key", None):
        configured.append("Anthropic")

    # Local provider is always available if configured
    if runtime.config.local_provider:
        configured.append("Local")

    if not configured:
        configured.append("None")

    import time
    from datetime import datetime

    status_text = (
        "[bold]VelixAgent Status[/bold]\n\n"
        f"Phase: 4 — Multimodal Input\n"
        f"Session: {runtime.session.session_id}\n\n"
    )

    fallback_chain = [provider.capitalize()]
    provider_chain = runtime.config.provider_chain
    if provider_chain:
        fallback_chain.extend(
            [fb.capitalize() for fb in provider_chain if fb.lower() != provider.lower()]
        )

    status_text += "Provider Chain:\n"
    for i, p_name in enumerate(fallback_chain, 1):
        status_text += f"{i}. {p_name} — available\n"

    status_text += "\nCooldowns:\n"

    from typing import Any

    active_provider: Any | None = getattr(runtime.agent, "_provider", None)
    cooldowns_dict = getattr(active_provider, "cooldowns", {}) if active_provider else {}

    current_time = time.time()
    for p_name in fallback_chain:
        p_lower = p_name.lower()
        expire_time = cooldowns_dict.get(p_lower, 0)
        if current_time < expire_time:
            expire_dt = datetime.fromtimestamp(expire_time)
            status_text += f"{p_name} — cooldown until {expire_dt.strftime('%H:%M:%S')}\n"
        else:
            if p_lower == "local" and active_provider:
                # Find LocalProvider instance
                local_prov = None
                if active_provider.primary_name == "local":
                    local_prov = active_provider.primary
                else:
                    for fb_name, fb_prov in active_provider.fallbacks:
                        if fb_name == "local":
                            local_prov = fb_prov
                            break
                if local_prov and hasattr(local_prov, "check_availability"):
                    is_avail, reason = local_prov.check_availability()
                    if not is_avail:
                        status_text += f"{p_name} — unavailable ({reason})\n"
                    else:
                        status_text += f"{p_name} — available\n"
                else:
                    status_text += f"{p_name} — available\n"
            else:
                status_text += f"{p_name} — available\n"

    runtime.console.print(status_text)
    return True


def handle_config(runtime: Runtime) -> bool:
    """Display the currently resolved configuration."""
    config = runtime.config
    runtime.console.print("\n[bold]Current Configuration:[/bold]\n")
    for field_name, value in config.model_dump().items():
        runtime.console.print(f"  [cyan]{field_name}[/cyan] = {value}")
    runtime.console.print()
    return True


def handle_version(runtime: Runtime) -> bool:
    """Display the application version."""
    print_info(runtime.console, f"VelixAgent v{__version__}")
    return True


def handle_exit(runtime: Runtime) -> bool:
    """Exit the REPL cleanly."""
    print_info(runtime.console, "Goodbye!")
    return False


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

COMMANDS: dict[str, Callable[[Runtime], bool]] = {
    "/help": handle_help,
    "/clear": handle_clear,
    "/status": handle_status,
    "/config": handle_config,
    "/version": handle_version,
    "/exit": handle_exit,
    "/quit": handle_exit,
}


def dispatch(runtime: Runtime, user_input: str) -> bool | None:
    """Route *user_input* to the appropriate command handler.

    Returns
    -------
    True   - continue the REPL loop
    False  - exit the REPL loop
    None   - input was not a slash command (caller should handle as task)
    """
    command = user_input.strip().lower()

    handler = COMMANDS.get(command)
    if handler is not None:
        return handler(runtime)

    if command.startswith("/run "):
        return handle_run(runtime, command[5:].strip())

    if command.startswith("/"):
        print_warning(runtime.console, f"Unknown command: {command}")
        return True

    # Not a slash command.
    return None
