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

import os
import pytest
from velix_agent.utils.paths import resolve_safe_path

class TestResolveSafePath:
    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        ws = tmp_path / "workspace"
        ws.mkdir()
        return ws

    def test_normal_file_inside_workspace(self, workspace: Path) -> None:
        (workspace / "file.txt").write_text("test")
        result = resolve_safe_path(workspace, "file.txt")
        assert result == workspace / "file.txt"

    def test_nested_path_inside_workspace(self, workspace: Path) -> None:
        nested = workspace / "nested" / "dir"
        nested.mkdir(parents=True)
        (nested / "file.txt").write_text("test")
        result = resolve_safe_path(workspace, "nested/dir/file.txt")
        assert result == nested / "file.txt"

    def test_parent_traversal_rejected(self, workspace: Path) -> None:
        with pytest.raises(PermissionError, match="outside the allowed workspace"):
            resolve_safe_path(workspace, "../outside.txt")

    def test_double_parent_traversal_rejected(self, workspace: Path) -> None:
        with pytest.raises(PermissionError, match="outside the allowed workspace"):
            resolve_safe_path(workspace, "../../outside.txt")

    def test_absolute_outside_path_rejected(self, workspace: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside.txt"
        with pytest.raises(PermissionError, match="outside the allowed workspace"):
            resolve_safe_path(workspace, str(outside))

    def test_existing_symlink_pointing_outside_workspace_rejected(self, workspace: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        symlink = workspace / "symlink.txt"
        os.symlink(str(outside), str(symlink))

        with pytest.raises(PermissionError, match="outside the allowed workspace"):
            resolve_safe_path(workspace, "symlink.txt")

    def test_symlink_pointing_inside_workspace_allowed(self, workspace: Path) -> None:
        inside = workspace / "inside.txt"
        inside.write_text("hello")
        symlink = workspace / "symlink.txt"
        os.symlink(str(inside), str(symlink))

        result = resolve_safe_path(workspace, "symlink.txt")
        assert result == inside.resolve()

    def test_nonexistent_file_inside_workspace_allowed(self, workspace: Path) -> None:
        result = resolve_safe_path(workspace, "new_file.txt", is_write=True)
        assert result == workspace / "new_file.txt"

    def test_nonexistent_path_parent_outside_workspace_rejected(self, workspace: Path) -> None:
        with pytest.raises(PermissionError, match="outside the allowed workspace"):
            resolve_safe_path(workspace, "../nonexistent_dir/new_file.txt", is_write=True)

    def test_git_write_attempt_rejected(self, workspace: Path) -> None:
        git_dir = workspace / ".git"
        git_dir.mkdir()
        with pytest.raises(PermissionError, match="Cannot access protected .git paths"):
            resolve_safe_path(workspace, ".git/config", is_write=True)

    def test_git_read_attempt_rejected(self, workspace: Path) -> None:
        git_dir = workspace / ".git"
        git_dir.mkdir()
        with pytest.raises(PermissionError, match="Cannot access protected .git paths"):
            resolve_safe_path(workspace, ".git/config")
