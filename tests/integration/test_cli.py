"""Integration tests for the VelixAgent CLI.

Uses Typer's CliRunner so we can test the full CLI without spawning
a subprocess. Tests do not depend on the user's real config directory.
"""

from __future__ import annotations

from typer.testing import CliRunner
from unittest.mock import patch

from velix_agent import __version__
from velix_agent.cli.app import app
from velix_agent.core.logging import reset_logging

runner = CliRunner()


class TestHelpCommand:
    """Test --help flag."""

    def test_help_exits_zero(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_help_contains_velix(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert "VelixAgent" in result.output


class TestVersionCommand:
    """Test --version flag."""

    def setup_method(self) -> None:
        reset_logging()

    def test_version_exits_zero(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0

    def test_version_shows_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert __version__ in result.output

    def test_version_short_flag(self) -> None:
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestConfigCommand:
    """Test the config subcommand."""

    def setup_method(self) -> None:
        reset_logging()

    def test_config_exits_zero(self) -> None:
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0

    def test_config_shows_debug(self) -> None:
        result = runner.invoke(app, ["config"])
        assert "debug" in result.output

    def test_config_shows_log_level(self) -> None:
        result = runner.invoke(app, ["config"])
        assert "log_level" in result.output

    def test_config_shows_history(self) -> None:
        result = runner.invoke(app, ["config"])
        assert "history_enabled" in result.output


class TestOneShotMode:
    """Test one-shot task execution."""

    def setup_method(self) -> None:
        reset_logging()

    @patch("velix_agent.core.application.AutonomousCodingLoop.run")
    def test_one_shot_exits_zero(self, mock_run) -> None:
        from velix_agent.orchestrator.models import OrchestratorState
        mock_run.return_value = OrchestratorState.COMPLETED
        result = runner.invoke(app, ["fix the failing tests"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with("fix the failing tests")

    @patch("velix_agent.core.application.AutonomousCodingLoop.run")
    def test_one_shot_shows_task(self, mock_run) -> None:
        from velix_agent.orchestrator.models import OrchestratorState
        mock_run.return_value = OrchestratorState.COMPLETED
        result = runner.invoke(app, ["What is VelixAgent?"])
        assert "Task completed successfully" in result.output

    @patch("velix_agent.core.application.AutonomousCodingLoop.run")
    def test_one_shot_shows_placeholder(self, mock_run) -> None:
        """Test that unknown task returns the mock provider fallback text."""
        from velix_agent.orchestrator.models import OrchestratorState
        mock_run.return_value = OrchestratorState.COMPLETED
        result = runner.invoke(app, ["Unknown task"])
        assert "Task completed successfully" in result.output

    @patch("velix_agent.core.application.AutonomousCodingLoop.run")
    def test_one_shot_with_debug(self, mock_run) -> None:
        from velix_agent.orchestrator.models import OrchestratorState
        mock_run.return_value = OrchestratorState.COMPLETED
        result = runner.invoke(app, ["--debug", "What is VelixAgent?"])
        assert result.exit_code == 0
        assert "Task completed successfully" in result.output


class TestDebugMode:
    """Test --debug flag behavior."""

    def setup_method(self) -> None:
        reset_logging()

    @patch("velix_agent.core.application.AutonomousCodingLoop.run")
    def test_debug_flag_exits_zero(self, mock_run) -> None:
        from velix_agent.orchestrator.models import OrchestratorState
        mock_run.return_value = OrchestratorState.COMPLETED
        result = runner.invoke(app, ["--debug", "test task"])
        assert result.exit_code == 0

    @patch("velix_agent.core.application.AutonomousCodingLoop.run")
    def test_debug_short_flag(self, mock_run) -> None:
        from velix_agent.orchestrator.models import OrchestratorState
        mock_run.return_value = OrchestratorState.COMPLETED
        result = runner.invoke(app, ["-d", "test task"])
        assert result.exit_code == 0
