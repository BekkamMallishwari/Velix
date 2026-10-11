"""
Production-grade Shadow Workspace Seeder for VelixAgent.

Creates an isolated shadow copy of a host workspace in a fresh temporary directory
without modifying the host workspace. Traverses component-by-component using
directory file descriptors and O_NOFOLLOW to mitigate TOCTOU races and symlink
traversals.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import IO, Callable, Optional

from velix_agent.core.logging import get_logger
from velix_agent.workspace.models import (
    SeedError,
    SeedErrorKind,
    SeedLimitExceeded,
    SeedResult,
)

logger = get_logger("workspace.seeder")

DEFAULT_MAX_FILES: int = 100_000
DEFAULT_MAX_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GiB

_GIT_EXACT: str = ".git"
_GIT_CASEFOLD: str = ".git"


def reliable_rmtree(root: Path | str) -> bool:
    """
    Reliably remove a directory tree, recovering from permission restrictions
    on read-only directories or files.

    Guarantees:
      - Symlinks inside the tree are unlinked without recursing into external targets.
      - Read-only files/directories inside the tree are granted write permissions to allow deletion.
      - Returns True if the directory was cleanly removed, False if any items remained.
    """
    root_path = Path(root).resolve()
    if not root_path.exists() and not root_path.is_symlink():
        return True

    def _on_exc(fn: Callable[[str], Any], path: str, exc: Any) -> None:
        p_obj = Path(path)
        try:
            # Only chmod if the path is not a symlink, to never affect an external target
            if not p_obj.is_symlink():
                os.chmod(path, stat.S_IRWXU)
        except OSError:
            pass

        parent = os.path.dirname(path)
        if parent:
            try:
                parent_obj = Path(parent)
                if not parent_obj.is_symlink():
                    os.chmod(parent, stat.S_IRWXU)
            except OSError:
                pass

        try:
            fn(path)
        except OSError as e:
            logger.warning("reliable_rmtree: retry failed for %s: %s", path, e)

    try:
        shutil.rmtree(str(root_path), onexc=_on_exc)
    except TypeError:
        # Fallback for Python < 3.12 without onexc keyword
        def _onerror(fn: Callable[[str], Any], path: str, exc_info: Any) -> None:
            _on_exc(fn, path, exc_info[1] if isinstance(exc_info, tuple) else exc_info)

        shutil.rmtree(str(root_path), onerror=_onerror)
    except Exception as e:
        logger.warning("reliable_rmtree: error removing %s: %s", root_path, e)

    if root_path.exists() or root_path.is_symlink():
        logger.error("reliable_rmtree: failed to completely remove directory: %s", root_path)
        return False
    return True


def check_platform_support() -> tuple[bool, str]:
    """
    Check if the host platform supports directory-FD traversal and atomic symlink protections.

    Returns (is_supported, details).
    On POSIX (Linux, macOS), supports_dir_fd, O_NOFOLLOW, O_DIRECTORY, and O_CLOEXEC
    must all be available for secure traversal.
    """
    missing = []
    if not (hasattr(os, "supports_dir_fd") and os.open in os.supports_dir_fd):
        missing.append("dir_fd in os.open")
    if not hasattr(os, "O_NOFOLLOW"):
        missing.append("O_NOFOLLOW")
    if not hasattr(os, "O_DIRECTORY"):
        missing.append("O_DIRECTORY")
    if not hasattr(os, "O_CLOEXEC"):
        missing.append("O_CLOEXEC")

    if missing:
        return False, f"Missing required platform capabilities: {', '.join(missing)}"
    return True, "POSIX directory-FD and O_NOFOLLOW traversal supported"


def is_git_name(name: str) -> bool:
    """
    Return True if this directory/file name matches or aliases a .git metadata name.

    Checks:
      1. Exact match (".git").
      2. Case-folded variants (".GIT", ".Git", etc.).
      3. All standard Unicode normalization forms (NFC, NFD, NFKC, NFKD).
      4. Trailing dots and spaces on case-insensitive / Windows-compatible filesystems.
    """
    if name == _GIT_EXACT:
        return True

    stripped = name.rstrip(". ")
    if stripped == _GIT_EXACT:
        return True

    for form in ("NFC", "NFD", "NFKC", "NFKD"):
        normalized = unicodedata.normalize(form, name).casefold()
        if normalized == _GIT_CASEFOLD or normalized.rstrip(". ") == _GIT_CASEFOLD:
            return True

    return False


def classify_symlink(
    link_abs_path: Path,
    workspace_root: Path,
) -> tuple[bool, str, bool]:
    """
    Classify a symlink's target as internal (safe) or escaping/git-targeting (unsafe).

    Returns (is_safe, target_str, is_git).
    is_safe is True iff the target is strictly internal to workspace_root and
    neither the target string nor the normalized destination touches .git or nested
    Git metadata.

    Strategy: pure path arithmetic — no filesystem calls on the target.
    """
    try:
        target_str = os.readlink(link_abs_path)
    except OSError:
        return False, "", False

    if not target_str or "\0" in target_str:
        return False, target_str, False

    if os.path.isabs(target_str):
        return False, target_str, False

    target_posix = PurePosixPath(target_str)
    if any(is_git_name(p) for p in target_posix.parts):
        return False, target_str, True

    link_parent = link_abs_path.parent
    candidate_str = os.path.normpath(str(link_parent / target_str))
    candidate_abs = Path(candidate_str)

    try:
        candidate_rel = candidate_abs.relative_to(workspace_root)
    except ValueError:
        return False, target_str, False

    if any(is_git_name(p) for p in candidate_rel.parts):
        return False, target_str, True

    return True, target_str, False


def safe_open_regular(
    workspace_root: Path,
    rel_path_str: str,
    *,
    workspace_root_fd: Optional[int] = None,
    pre_open_hook: Optional[Callable[[str], None]] = None,
) -> tuple[IO[bytes], os.stat_result]:
    """
    Open a regular file securely using directory-FD-relative traversal and
    O_NOFOLLOW on every path component on POSIX platforms.

    Verifies each directory component with fstat(S_ISDIR) and the final leaf
    with fstat(S_ISREG). Intermediate FDs are closed.
    """
    if not rel_path_str or "\0" in rel_path_str:
        raise ValueError(f"Invalid relative path: {rel_path_str!r}")

    rel_posix = PurePosixPath(rel_path_str)
    if rel_posix.is_absolute():
        raise ValueError(f"Path must be relative, got: {rel_path_str!r}")

    parts = rel_posix.parts
    if not parts or any(p in (".", "..", "") for p in parts):
        raise ValueError(f"Path contains invalid components: {rel_path_str!r}")

    supports_dir_fd = (
        hasattr(os, "supports_dir_fd")
        and os.open in os.supports_dir_fd
        and hasattr(os, "O_NOFOLLOW")
    )
    if not supports_dir_fd:
        raise OSError("Secure directory-FD traversal is not supported on this platform")

    own_root_fd = False
    if workspace_root_fd is not None:
        root_fd = workspace_root_fd
    else:
        root_fd = os.open(
            str(workspace_root),
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        own_root_fd = True

    close_stack: list[int] = []
    if own_root_fd:
        close_stack.append(root_fd)

    try:
        if pre_open_hook is not None:
            pre_open_hook(rel_path_str)

        current_dfd = root_fd
        for part in parts[:-1]:
            next_dfd = os.open(
                part,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=current_dfd,
            )
            close_stack.append(next_dfd)
            st_dir = os.fstat(next_dfd)
            if not stat.S_ISDIR(st_dir.st_mode):
                raise OSError(f"Path component {part!r} is not a directory")
            current_dfd = next_dfd

        leaf = parts[-1]
        file_fd = os.open(
            leaf,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=current_dfd,
        )
        try:
            st_file = os.fstat(file_fd)
            if not stat.S_ISREG(st_file.st_mode):
                raise OSError(f"Path {rel_path_str!r} is not a regular file (st_mode=0o{st_file.st_mode:o})")
            file_obj = os.fdopen(file_fd, "rb")
        except Exception:
            try:
                os.close(file_fd)
            except OSError:
                pass
            raise

        return file_obj, st_file
    finally:
        for fd in close_stack:
            try:
                os.close(fd)
            except OSError:
                pass


def copy_regular_file(
    workspace_root: Path,
    rel_path_str: str,
    dst: Path,
    *,
    chunk_size: int = 65536,
    max_bytes: int = DEFAULT_MAX_BYTES,
    bytes_already_copied: int = 0,
    workspace_root_fd: Optional[int] = None,
    pre_open_hook: Optional[Callable[[str], None]] = None,
    pre_chunk_hook: Optional[Callable[[str], None]] = None,
) -> int:
    """
    Copy workspace_root/rel_path_str -> dst using directory-FD-relative
    traversal with O_NOFOLLOW on all components.

    Enforces remaining byte budget on every chunk before writing.
    Detects source file size, inode, and nanosecond metadata changes during copying via fstat.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    remaining_budget = max_bytes - bytes_already_copied
    if remaining_budget < 0:
        raise SeedLimitExceeded(f"max_bytes={max_bytes} already exceeded")

    bytes_written = 0
    src_f, st_initial = safe_open_regular(
        workspace_root,
        rel_path_str,
        workspace_root_fd=workspace_root_fd,
        pre_open_hook=pre_open_hook,
    )
    try:
        with src_f:
            with open(dst, "wb") as dst_f:
                while True:
                    if pre_chunk_hook is not None:
                        pre_chunk_hook(rel_path_str)
                    chunk = src_f.read(chunk_size)
                    if not chunk:
                        break
                    if bytes_written + len(chunk) > remaining_budget:
                        raise SeedLimitExceeded(
                            f"max_bytes={max_bytes} exceeded while copying {rel_path_str!r} "
                            f"({bytes_already_copied + bytes_written + len(chunk)} > {max_bytes})"
                        )
                    dst_f.write(chunk)
                    bytes_written += len(chunk)

            st_final = os.fstat(src_f.fileno())
            if st_final.st_size != st_initial.st_size:
                raise OSError(
                    f"Source file {rel_path_str!r} changed size during copy: "
                    f"initial {st_initial.st_size} bytes, final {st_final.st_size} bytes"
                )
            if st_final.st_ino != st_initial.st_ino or st_final.st_dev != st_initial.st_dev:
                raise OSError(
                    f"Source file {rel_path_str!r} inode changed during copy"
                )
            init_mtime = getattr(st_initial, "st_mtime_ns", st_initial.st_mtime)
            final_mtime = getattr(st_final, "st_mtime_ns", st_final.st_mtime)
            if final_mtime != init_mtime:
                raise OSError(
                    f"Source file {rel_path_str!r} modification time changed during copy: "
                    f"initial {init_mtime}, final {final_mtime}"
                )
            init_ctime = getattr(st_initial, "st_ctime_ns", getattr(st_initial, "st_ctime", None))
            final_ctime = getattr(st_final, "st_ctime_ns", getattr(st_final, "st_ctime", None))
            if init_ctime is not None and final_ctime is not None and final_ctime != init_ctime:
                raise OSError(
                    f"Source file {rel_path_str!r} status change time changed during copy: "
                    f"initial {init_ctime}, final {final_ctime}"
                )
    except BaseException:
        if dst.exists() or dst.is_symlink():
            try:
                dst.unlink()
            except OSError:
                pass
        raise

    try:
        shutil.copystat(str(workspace_root / rel_path_str), str(dst), follow_symlinks=False)
    except OSError:
        pass
    return bytes_written


def seed_shadow(
    workspace_root: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    tmp_dir: Optional[Path] = None,
    _pre_open_hook: Optional[Callable[[str], None]] = None,
    _pre_chunk_hook: Optional[Callable[[str], None]] = None,
) -> SeedResult:
    """
    Create a shadow copy of workspace_root in a fresh temporary directory.

    Guarantees:
      - The source workspace is opened exclusively read-only and never modified.
      - On any limit violation or unhandled exception, partial shadow directories are wiped.
      - .git and nested Git metadata are never copied into the shadow.
    """
    is_supported, reason = check_platform_support()
    if not is_supported:
        raise OSError(f"Platform cannot safely execute shadow seeding: {reason}")

    workspace_root = workspace_root.resolve()
    if not workspace_root.is_dir():
        raise ValueError(f"workspace_root is not an existing directory: {workspace_root}")

    shadow_root = Path(tempfile.mkdtemp(prefix="velix_shadow_", dir=tmp_dir))
    result = SeedResult(shadow_root=shadow_root)

    try:
        kwargs = {}
        if _pre_open_hook is not None:
            kwargs["_pre_open_hook"] = _pre_open_hook
        if _pre_chunk_hook is not None:
            kwargs["_pre_chunk_hook"] = _pre_chunk_hook
        _seed_inner(workspace_root, shadow_root, result, max_files, max_bytes, **kwargs)
    except BaseException:
        reliable_rmtree(shadow_root)
        raise

    return result


def _seed_inner(
    workspace_root: Path,
    shadow_root: Path,
    result: SeedResult,
    max_files: int,
    max_bytes: int,
    _pre_open_hook: Optional[Callable[[str], None]] = None,
    _pre_chunk_hook: Optional[Callable[[str], None]] = None,
) -> None:
    """Core traversal and copy logic."""
    root_fd = os.open(
        str(workspace_root),
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        for root_str, dirs, files in os.walk(str(workspace_root), followlinks=False):
            root_abs = Path(root_str)
            rel_root = root_abs.relative_to(workspace_root)

            filtered_dirs: list[str] = []
            symlink_dirs: list[str] = []
            for dname in list(dirs):
                d_abs = root_abs / dname
                if is_git_name(dname):
                    rel_p = str(rel_root / dname) if str(rel_root) != "." else dname
                    result.errors.append(
                        SeedError(rel_p, SeedErrorKind.GIT_EXCLUDED, f"Excluded: {dname!r}")
                    )
                elif d_abs.is_symlink():
                    symlink_dirs.append(dname)
                else:
                    filtered_dirs.append(dname)
            dirs[:] = filtered_dirs
            files.extend(symlink_dirs)

            if str(rel_root) != ".":
                shadow_dir = shadow_root / rel_root
                shadow_dir.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copystat(str(root_abs), str(shadow_dir), follow_symlinks=False)
                except OSError:
                    pass
                result.dirs_created += 1
                result.files_copied += 1
                if result.files_copied > max_files:
                    raise SeedLimitExceeded(
                        f"max_files={max_files} exceeded at {rel_root}"
                    )

            for name in files:
                src_abs = root_abs / name
                rel_path_str = str(rel_root / name) if str(rel_root) != "." else name

                try:
                    candidate = workspace_root / rel_path_str
                    candidate.relative_to(workspace_root)
                except ValueError:
                    result.errors.append(
                        SeedError(rel_path_str, SeedErrorKind.PATH_TRAVERSAL,
                                  "Computed path escapes workspace_root")
                    )
                    continue

                try:
                    st = src_abs.lstat()
                except OSError as exc:
                    result.errors.append(
                        SeedError(rel_path_str, SeedErrorKind.READ_ERROR, str(exc))
                    )
                    continue

                if is_git_name(name):
                    result.errors.append(
                        SeedError(rel_path_str, SeedErrorKind.GIT_EXCLUDED,
                                  f"Excluded file named {name!r}")
                    )
                    continue

                mode = st.st_mode

                if stat.S_ISLNK(mode):
                    is_safe, target_str, is_git = classify_symlink(src_abs, workspace_root)
                    if not is_safe:
                        if is_git:
                            result.errors.append(
                                SeedError(rel_path_str, SeedErrorKind.GIT_EXCLUDED,
                                          f"Symlink targets Git metadata: {target_str!r}")
                            )
                        else:
                            result.errors.append(
                                SeedError(rel_path_str, SeedErrorKind.SYMLINK_ESCAPING,
                                          f"Escaping target: {target_str!r}")
                            )
                        continue

                    dst_abs = shadow_root / rel_path_str
                    dst_abs.parent.mkdir(parents=True, exist_ok=True)
                    if dst_abs.exists() or dst_abs.is_symlink():
                        dst_abs.unlink()
                    os.symlink(target_str, str(dst_abs))
                    result.symlinks_copied += 1
                    result.files_copied += 1
                    if result.files_copied > max_files:
                        raise SeedLimitExceeded(
                            f"max_files={max_files} exceeded at {rel_path_str}"
                        )
                    continue

                if not stat.S_ISREG(mode):
                    kind = SeedErrorKind.SPECIAL_FILE
                    detail = f"st_mode=0o{mode:o}"
                    result.errors.append(SeedError(rel_path_str, kind, detail))
                    continue

                if result.bytes_copied + st.st_size > max_bytes:
                    raise SeedLimitExceeded(
                        f"max_bytes={max_bytes} would be exceeded at {rel_path_str} "
                        f"(file size {st.st_size})"
                    )

                dst_abs = shadow_root / rel_path_str
                try:
                    written = copy_regular_file(
                        workspace_root,
                        rel_path_str,
                        dst_abs,
                        max_bytes=max_bytes,
                        bytes_already_copied=result.bytes_copied,
                        workspace_root_fd=root_fd,
                        pre_open_hook=_pre_open_hook,
                        pre_chunk_hook=_pre_chunk_hook,
                    )
                except SeedLimitExceeded:
                    raise
                except OSError as exc:
                    result.errors.append(
                        SeedError(rel_path_str, SeedErrorKind.READ_ERROR, str(exc))
                    )
                    continue

                result.bytes_copied += written
                result.files_copied += 1
                if result.files_copied > max_files:
                    raise SeedLimitExceeded(
                        f"max_files={max_files} exceeded at {rel_path_str}"
                    )
    finally:
        try:
            os.close(root_fd)
        except OSError:
            pass
