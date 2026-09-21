"""Cross-platform path utilities for VelixAgent.

Uses platformdirs for OS-appropriate application directories and pathlib
for safe, portable path construction. Never hardcodes user-specific paths.
"""

from pathlib import Path

import platformdirs

APP_NAME = "velix-agent"
APP_AUTHOR = "VelixAgent"


def get_config_dir() -> Path:
    """Return the platform-specific configuration directory.

    - macOS:   ~/Library/Application Support/velix-agent
    - Linux:   ~/.config/velix-agent
    - Windows: C:\\Users\\<user>\\AppData\\Local\\velix-agent
    """
    return Path(platformdirs.user_config_dir(APP_NAME, APP_AUTHOR))


def get_data_dir() -> Path:
    """Return the platform-specific data directory.

    - macOS:   ~/Library/Application Support/velix-agent
    - Linux:   ~/.local/share/velix-agent
    - Windows: C:\\Users\\<user>\\AppData\\Local\\velix-agent
    """
    return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))


def get_history_dir() -> Path:
    """Return the directory where command history is stored."""
    return get_data_dir() / "history"


def get_default_history_file() -> Path:
    """Return the default path for the REPL history file."""
    return get_history_dir() / "repl_history"


def ensure_parent_exists(path: Path) -> Path:
    """Create parent directories for *path* if they do not exist.

    Returns the original path for convenient chaining.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def expand_path(path: Path | str) -> Path:
    """Expand ``~`` and resolve the given path."""
    return Path(path).expanduser().resolve()
