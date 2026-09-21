"""Tests for velix_agent.utils.paths."""

from __future__ import annotations

from pathlib import Path

from velix_agent.utils.paths import (
    ensure_parent_exists,
    expand_path,
    get_config_dir,
    get_data_dir,
    get_default_history_file,
    get_history_dir,
)


class TestPlatformDirs:
    """Test that platformdirs-based helpers return sensible paths."""

    def test_config_dir_is_absolute(self) -> None:
        assert get_config_dir().is_absolute()

    def test_data_dir_is_absolute(self) -> None:
        assert get_data_dir().is_absolute()

    def test_history_dir_is_under_data_dir(self) -> None:
        history_dir = get_history_dir()
        data_dir = get_data_dir()
        assert str(history_dir).startswith(str(data_dir))

    def test_default_history_file_name(self) -> None:
        assert get_default_history_file().name == "repl_history"

    def test_default_history_file_is_under_history_dir(self) -> None:
        history_file = get_default_history_file()
        history_dir = get_history_dir()
        assert history_file.parent == history_dir

    def test_config_dir_contains_app_name(self) -> None:
        config_dir = get_config_dir()
        assert "velix-agent" in str(config_dir)


class TestExpandPath:
    """Test tilde expansion and resolution."""

    def test_expand_tilde(self) -> None:
        result = expand_path("~/something")
        assert "~" not in str(result)
        assert result.is_absolute()

    def test_expand_absolute_path(self) -> None:
        result = expand_path("/tmp/test")
        assert result == Path("/tmp/test").resolve()

    def test_expand_returns_path(self) -> None:
        result = expand_path("relative/path")
        assert isinstance(result, Path)
        assert result.is_absolute()


class TestEnsureParentExists:
    """Test safe parent-directory creation."""

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c" / "file.txt"
        result = ensure_parent_exists(target)
        assert result == target
        assert target.parent.exists()

    def test_idempotent_when_parent_exists(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        ensure_parent_exists(target)
        ensure_parent_exists(target)  # Should not raise.
        assert target.parent.exists()

    def test_returns_original_path(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "file.txt"
        result = ensure_parent_exists(target)
        assert result is target
