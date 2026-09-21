"""Tests for velix_agent.core.config."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from velix_agent.core.config import VelixConfig


class TestVelixConfigDefaults:
    """Test default configuration values."""

    def test_debug_default(self) -> None:
        config = VelixConfig()
        assert config.debug is False

    def test_log_level_default(self) -> None:
        config = VelixConfig()
        assert config.log_level == "WARNING"

    def test_history_enabled_default(self) -> None:
        config = VelixConfig()
        assert config.history_enabled is True

    def test_history_file_default_is_path(self) -> None:
        config = VelixConfig()
        assert isinstance(config.history_file, Path)

    def test_history_file_contains_repl_history(self) -> None:
        config = VelixConfig()
        assert config.history_file.name == "repl_history"


class TestVelixConfigEnvOverrides:
    """Test that environment variables correctly override defaults."""

    def test_debug_from_env(self) -> None:
        with patch.dict(os.environ, {"VELIX_DEBUG": "true"}, clear=False):
            config = VelixConfig()
            assert config.debug is True

    def test_log_level_from_env(self) -> None:
        with patch.dict(os.environ, {"VELIX_LOG_LEVEL": "DEBUG"}, clear=False):
            config = VelixConfig()
            assert config.log_level == "DEBUG"

    def test_history_enabled_from_env(self) -> None:
        with patch.dict(os.environ, {"VELIX_HISTORY_ENABLED": "false"}, clear=False):
            config = VelixConfig()
            assert config.history_enabled is False

    def test_history_file_from_env(self, tmp_path: Path) -> None:
        custom_path = str(tmp_path / "custom_history")
        with patch.dict(os.environ, {"VELIX_HISTORY_FILE": custom_path}, clear=False):
            config = VelixConfig()
            assert config.history_file == Path(custom_path)


class TestVelixConfigPrecedence:
    """Test configuration precedence: CLI overrides > env > defaults."""

    def test_model_copy_overrides_env(self) -> None:
        with patch.dict(os.environ, {"VELIX_DEBUG": "true"}, clear=False):
            config = VelixConfig()
            assert config.debug is True

            # Simulate CLI override.
            overridden = config.model_copy(update={"debug": False})
            assert overridden.debug is False

    def test_model_copy_preserves_other_fields(self) -> None:
        config = VelixConfig()
        overridden = config.model_copy(update={"debug": True})
        assert overridden.debug is True
        assert overridden.log_level == config.log_level
        assert overridden.history_enabled == config.history_enabled


class TestVelixConfigExtraFields:
    """Test that unknown fields are ignored (future-proofing)."""

    def test_extra_env_vars_ignored(self) -> None:
        with patch.dict(os.environ, {"VELIX_UNKNOWN_FIELD": "value"}, clear=False):
            config = VelixConfig()
            assert not hasattr(config, "unknown_field")
