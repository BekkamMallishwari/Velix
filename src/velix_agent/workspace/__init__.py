"""Workspace package providing shadow isolation and safe file management."""

from velix_agent.workspace.models import (
    SeedError,
    SeedErrorKind,
    SeedLimitExceeded,
    SeedResult,
    SeedingFailedError,
)

__all__ = [
    "SeedError",
    "SeedErrorKind",
    "SeedLimitExceeded",
    "SeedResult",
    "SeedingFailedError",
]
