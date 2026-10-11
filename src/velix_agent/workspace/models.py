"""Workspace models and configuration for isolated shadow execution."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from velix_agent.core.errors import VelixError


class SeedErrorKind(str, Enum):
    """Classification of non-fatal errors or skips during seeding."""
    GIT_EXCLUDED = "git_excluded"
    SYMLINK_ESCAPING = "symlink_escaping"
    SYMLINK_LOOP = "symlink_loop"
    SPECIAL_FILE = "special_file"
    READ_ERROR = "read_error"
    PATH_TRAVERSAL = "path_traversal"


FATAL_ERROR_KINDS: set[SeedErrorKind] = {
    SeedErrorKind.READ_ERROR,
    SeedErrorKind.PATH_TRAVERSAL,
    SeedErrorKind.SYMLINK_LOOP,
}


@dataclass
class SeedError:
    """Records a skipped or problematic path during seeding."""
    rel_path: str
    kind: SeedErrorKind
    detail: str = ""


@dataclass
class SeedResult:
    """Returned on seeding completion."""
    shadow_root: Path
    files_copied: int = 0
    bytes_copied: int = 0
    dirs_created: int = 0
    symlinks_copied: int = 0
    errors: list[SeedError] = field(default_factory=list)

    @property
    def fatal_errors(self) -> list[SeedError]:
        """Errors that indicate an incomplete or compromised shadow workspace."""
        return [e for e in self.errors if e.kind in FATAL_ERROR_KINDS]

    def ok(self) -> bool:
        """Return True if no fatal errors occurred during seeding."""
        return len(self.fatal_errors) == 0


class SeedLimitExceeded(RuntimeError):
    """Raised when max_files or max_bytes is exceeded during seeding."""


class SeedingFailedError(VelixError):
    """Raised when shadow workspace seeding encounters fatal errors."""

    def __init__(self, message: str, errors: list[SeedError] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []
