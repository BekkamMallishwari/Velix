"""Integration tests for the VelixAgent REPL.

Tests exercise the slash-command dispatch logic and REPL-level input
handling without actually launching a full prompt_toolkit session.
"""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from velix_agent import __version__
from velix_agent.cli.commands import dispatch
from velix_agent.cli.console import print_task_placeholder
from velix_agent.core.config import VelixConfig
from velix_agent.core.logging import reset_logging
from velix_agent.core.runtime import Runtime


def _make_runtime() -> Runtime:
    """Create a Runtime with a captured console (no real terminal)."""
    reset_logging()
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=120, highlight=False)
    config = VelixConfig()
    return Runtime(config=config, console=console)


def _get_output(runtime: Runtime) -> str:
    """Extract captured output from the Runtime's console."""
    runtime.console.file.seek(0)  # type: ignore[union-attr]
    return runtime.console.file.read()  # type: ignore[union-attr]


class TestHelpCommand:
    """Test /help command."""

    def test_returns_true(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "/help") is True

    def test_output_contains_commands(self) -> None:
        runtime = _make_runtime()
        dispatch(runtime, "/help")
        output = _get_output(runtime)
        assert "help" in output
        assert "exit" in output
        assert "config" in output
        assert "version" in output


class TestClearCommand:
    """Test /clear command."""

    def test_returns_true(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "/clear") is True


class TestConfigCommand:
    """Test /config command."""

    def test_returns_true(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "/config") is True

    def test_output_contains_fields(self) -> None:
        runtime = _make_runtime()
        dispatch(runtime, "/config")
        output = _get_output(runtime)
        assert "debug" in output
        assert "log_level" in output
        assert "history_enabled" in output


class TestVersionCommand:
    """Test /version command."""

    def test_returns_true(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "/version") is True

    def test_output_contains_version(self) -> None:
        runtime = _make_runtime()
        dispatch(runtime, "/version")
        output = _get_output(runtime)
        assert __version__ in output


class TestExitCommand:
    """Test /exit command."""

    def test_returns_false(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "/exit") is False

    def test_output_contains_goodbye(self) -> None:
        runtime = _make_runtime()
        dispatch(runtime, "/exit")
        output = _get_output(runtime)
        assert "Goodbye" in output


class TestQuitCommand:
    """Test /quit command."""

    def test_returns_false(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "/quit") is False


class TestUnknownSlashCommand:
    """Test unknown slash commands."""

    def test_returns_true(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "/unknown") is True

    def test_output_contains_unknown(self) -> None:
        runtime = _make_runtime()
        dispatch(runtime, "/unknown")
        output = _get_output(runtime)
        assert "Unknown command" in output
        assert "/unknown" in output


class TestNonSlashInput:
    """Test that non-slash text returns None (task delegation)."""

    def test_plain_text_returns_none(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "fix the tests") is None

    def test_empty_string_returns_none(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "") is None


class TestEmptyAndWhitespace:
    """Test that empty/whitespace input is handled."""

    def test_whitespace_only_returns_none(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "   ") is None


class TestTaskPlaceholder:
    """Test that task placeholder renders correctly."""

    def test_placeholder_contains_task(self) -> None:
        runtime = _make_runtime()
        print_task_placeholder(runtime.console, "fix the failing tests")
        output = _get_output(runtime)
        assert "fix the failing tests" in output
        assert "not available yet" in output


class TestCaseInsensitivity:
    """Test that commands are case-insensitive."""

    def test_uppercase_help(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "/HELP") is True

    def test_mixed_case_exit(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "/Exit") is False

    def test_uppercase_config(self) -> None:
        runtime = _make_runtime()
        assert dispatch(runtime, "/CONFIG") is True
