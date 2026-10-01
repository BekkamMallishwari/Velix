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


def resolve_safe_path(
    workspace_root: Path | str, target_path: Path | str, is_write: bool = False
) -> Path:
    """Resolve and validate a path against the workspace boundary and security rules.

    Raises PermissionError if the path violates security boundaries.
    """
    workspace = Path(workspace_root).resolve()
    path = Path(target_path)

    if not path.is_absolute():
        path = workspace / path

    resolved_path = path.resolve()

    # 1. Workspace boundary check
    if not resolved_path.is_relative_to(workspace):
        raise PermissionError(f"Access denied: {target_path} is outside the allowed workspace.")

    # 2. .git protection
    if ".git" in resolved_path.parts:
        raise PermissionError("Access denied: Cannot access protected .git paths.")

    # 3. Sensitive directories protection (explicit block just in case workspace allows it)
    sensitive_paths = [
        Path.home() / ".ssh",
        Path.home() / ".aws",
        Path.home() / ".config",
        Path("/etc/passwd"),
        Path("/private/etc/passwd"),
        Path("/private/etc/master.passwd"),
    ]

    for sensitive in sensitive_paths:
        try:
            resolved_sensitive = sensitive.resolve()
            if resolved_path == resolved_sensitive or resolved_path.is_relative_to(
                resolved_sensitive
            ):
                raise PermissionError(
                    f"Access denied: Path intersects with sensitive location {sensitive}"
                )
        except Exception:
            pass

    return resolved_path
