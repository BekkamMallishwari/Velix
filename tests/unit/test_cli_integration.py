"""Tests for CLI integration with AutonomousCodingLoop."""

import pytest
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from velix_agent.cli.app import app
from velix_agent.orchestrator.models import OrchestratorState

runner = CliRunner()


@patch("velix_agent.core.application.AutonomousCodingLoop.run")
def test_cli_one_shot_success(mock_run: MagicMock) -> None:
    mock_run.return_value = OrchestratorState.COMPLETED

    with patch("velix_agent.core.agent.Agent.respond") as mock_respond:
        result = runner.invoke(app, ["test_task"])

        assert result.exit_code == 0
        mock_run.assert_called_once_with("test_task")
        mock_respond.assert_not_called()
        assert "Task completed successfully." in result.stdout


@patch("velix_agent.core.application.AutonomousCodingLoop.run")
def test_cli_one_shot_failed(mock_run: MagicMock) -> None:
    mock_run.return_value = OrchestratorState.FAILED

    result = runner.invoke(app, ["test_task"])

    assert result.exit_code == 1
    mock_run.assert_called_once_with("test_task")
    assert "Task failed." in result.stdout


@patch("velix_agent.core.application.AutonomousCodingLoop.run")
def test_cli_one_shot_blocked(mock_run: MagicMock) -> None:
    mock_run.return_value = OrchestratorState.BLOCKED

    result = runner.invoke(app, ["test_task"])

    assert result.exit_code == 1
    mock_run.assert_called_once_with("test_task")
    assert "Task blocked due to missing capabilities." in result.stdout


@patch("velix_agent.cli.repl.start_repl")
def test_cli_repl_isolation(mock_start_repl: MagicMock) -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    mock_start_repl.assert_called_once()


@patch("velix_agent.core.application.AutonomousCodingLoop.run")
def test_cli_one_shot_seeding_failed_error(mock_run: MagicMock) -> None:
    from velix_agent.workspace.models import SeedError, SeedErrorKind, SeedingFailedError

    fatal_err = SeedError("bad_file.txt", SeedErrorKind.READ_ERROR, "Permission denied")
    mock_run.side_effect = SeedingFailedError(
        "Shadow workspace seeding failed with fatal error(s): bad_file.txt: Permission denied",
        errors=[fatal_err],
    )

    result = runner.invoke(app, ["test_task"])

    assert result.exit_code == 1
    assert "Unexpected error" not in result.stdout
    assert "Shadow workspace seeding failed with fatal error(s):" in result.stdout
    assert "bad_file.txt" in result.stdout
    assert "Permission denied" in result.stdout


@patch("velix_agent.core.application.AutonomousCodingLoop.run")
def test_cli_one_shot_seeding_failed_error_debug_mode(mock_run: MagicMock) -> None:
    from velix_agent.workspace.models import SeedError, SeedErrorKind, SeedingFailedError

    fatal_err = SeedError("bad_file.txt", SeedErrorKind.READ_ERROR, "Permission denied")
    mock_run.side_effect = SeedingFailedError(
        "Shadow workspace seeding failed with fatal error(s): bad_file.txt: Permission denied",
        errors=[fatal_err],
    )

    result = runner.invoke(app, ["--debug", "test_task"])

    assert result.exit_code != 0
    assert result.exception is not None
    assert isinstance(result.exception, SeedingFailedError)
