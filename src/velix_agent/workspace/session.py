"""
Shadow Workspace Session context manager.

Manages creation, execution binding, and clean teardown of temporary shadow
workspaces. Ensures the host workspace is never modified during execution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from velix_agent.core.logging import get_logger
from velix_agent.workspace.models import SeedResult, SeedingFailedError
from velix_agent.workspace.seeder import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_FILES,
    reliable_rmtree,
    seed_shadow,
)

logger = get_logger("workspace.session")


class ShadowWorkspaceSession:
    """
    Context manager for isolated agent execution inside a shadow copy of the workspace.

    On entry, seeds a fresh temporary copy of host_workspace.
    On exit (including errors or cancellation), cleans up the shadow copy.
    """

    def __init__(
        self,
        host_workspace: Path | str,
        *,
        max_files: int = DEFAULT_MAX_FILES,
        max_bytes: int = DEFAULT_MAX_BYTES,
        tmp_dir: Optional[Path] = None,
        keep_on_success: bool = False,
        _pre_open_hook: Optional[Callable[[str], None]] = None,
        _pre_chunk_hook: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.host_workspace = Path(host_workspace).resolve()
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.tmp_dir = tmp_dir
        self.keep_on_success = keep_on_success
        self._pre_open_hook = _pre_open_hook
        self._pre_chunk_hook = _pre_chunk_hook

        self.seed_result: Optional[SeedResult] = None
        self.shadow_root: Optional[Path] = None

    def __enter__(self) -> Path:
        self.seed_result = seed_shadow(
            self.host_workspace,
            max_files=self.max_files,
            max_bytes=self.max_bytes,
            tmp_dir=self.tmp_dir,
            _pre_open_hook=self._pre_open_hook,
            _pre_chunk_hook=self._pre_chunk_hook,
        )
        self.shadow_root = self.seed_result.shadow_root
        if not self.seed_result.ok():
            fatal = self.seed_result.fatal_errors
            if self.shadow_root and self.shadow_root.exists():
                reliable_rmtree(self.shadow_root)
            self.shadow_root = None
            err_details = "; ".join(f"{e.rel_path}: {e.detail}" for e in fatal)
            raise SeedingFailedError(
                f"Shadow workspace seeding failed with fatal error(s): {err_details}",
                errors=fatal,
            )
        return self.shadow_root

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.shadow_root is not None and self.shadow_root.exists():
            if exc_type is not None or not self.keep_on_success:
                success = reliable_rmtree(self.shadow_root)
                if not success:
                    logger.error("Failed to cleanly remove shadow workspace at %s", self.shadow_root)
