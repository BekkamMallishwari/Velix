"""Tests for velix_agent.core.runtime."""

from __future__ import annotations

import os
from unittest.mock import patch

from rich.console import Console

from velix_agent.core.config import VelixConfig
from velix_agent.core.logging import reset_logging
from velix_agent.core.runtime import Runtime


class TestRuntimeCreation:
    """Test Runtime.create() factory method."""

    def setup_method(self) -> None:
        reset_logging()

    def test_create_returns_runtime(self) -> None:
        runtime = Runtime.create()
        assert isinstance(runtime, Runtime)

    def test_create_has_config(self) -> None:
        runtime = Runtime.create()
        assert isinstance(runtime.config, VelixConfig)

    def test_create_has_console(self) -> None:
        runtime = Runtime.create()
        assert isinstance(runtime.console, Console)

    def test_create_custom_console(self) -> None:
        custom = Console(force_terminal=True)
        runtime = Runtime.create(console=custom)
        assert runtime.console is custom


class TestRuntimeDebug:
    """Test debug mode propagation."""

    def setup_method(self) -> None:
        reset_logging()

    def test_debug_default_false(self) -> None:
        runtime = Runtime.create()
        assert runtime.debug is False

    def test_debug_from_cli_override(self) -> None:
        runtime = Runtime.create(debug=True)
        assert runtime.debug is True
        assert runtime.config.debug is True

    def test_debug_sets_log_level_to_debug(self) -> None:
        runtime = Runtime.create(debug=True)
        assert runtime.config.log_level == "DEBUG"

    def test_debug_from_env(self) -> None:
        reset_logging()
        with patch.dict(os.environ, {"VELIX_DEBUG": "true"}, clear=False):
            runtime = Runtime.create()
            assert runtime.debug is True

    def test_debug_cli_override_beats_env(self) -> None:
        reset_logging()
        with patch.dict(os.environ, {"VELIX_DEBUG": "true"}, clear=False):
            runtime = Runtime.create(debug=False)
            assert runtime.debug is False
