"""
Bounded sandbox security tests.

Coverage:
    - Workspace boundary enforcement (read & write)
    - Network denial (outbound + localhost)
    - Credential protection (SSH, AWS, .kube, .npmrc, .docker, .gcp, .netrc)
    - .git directory protection (where supported)
    - Command timeout enforcement
    - Output size limits (stdout + stderr)
    - Child-process cleanup / runaway reaping
    - Environment stripping (no host secrets leaked)
    - Fail-closed on None backend

Capability rules:
    - Tests that require ``filesystem_isolation`` skip on platforms that do
      not report it as SUPPORTED.
    - Tests that require ``network_isolation`` skip on platforms that do not
      report it as SUPPORTED.
    - Tests that require ``timeout`` skip on platforms that do not report it.
    - Tests that require ``output_limit`` skip on platforms that do not report it.
    - We NEVER infer that a capability is supported just because a test was
      skipped or because a binary happens to be present.

Windows limitations (documented, not tested here):
    - Filesystem isolation: UNSUPPORTED on the Windows Job Object backend.
    - Network isolation:    UNSUPPORTED on the Windows Job Object backend.
    - No tests in this file assert those protections on Windows.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

import pytest

from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.result import SandboxError

# ---------------------------------------------------------------------------
# Helpers / markers
# ---------------------------------------------------------------------------

_SYSTEM = platform.system()


def _caps() -> object:
    """Return the capabilities of the default SandboxManager."""
    return SandboxManager().get_capabilities()


def _needs_fs_isolation(caps: object) -> bool:
    return getattr(caps, "filesystem_isolation", "NOT_AVAILABLE") == "SUPPORTED"


def _needs_net_isolation(caps: object) -> bool:
    return getattr(caps, "network_isolation", "NOT_AVAILABLE") == "SUPPORTED"


def _needs_timeout(caps: object) -> bool:
    return getattr(caps, "timeout", "NOT_AVAILABLE") == "SUPPORTED"


def _needs_output_limit(caps: object) -> bool:
    return getattr(caps, "output_limit", "NOT_AVAILABLE") == "SUPPORTED"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def caps() -> object:
    return _caps()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".git").mkdir()
    (ws / "test.txt").write_text("hello")
    return ws


@pytest.fixture
def manager() -> SandboxManager:
    return SandboxManager()


# ---------------------------------------------------------------------------
# Fail-closed: None backend must raise SandboxError
# ---------------------------------------------------------------------------


def test_sandbox_fail_closed_none_backend() -> None:
    """A manager with no backend must raise SandboxError, not silently succeed."""
    mgr = SandboxManager(_force_none=True)
    with pytest.raises(SandboxError, match="unavailable"):
        mgr.execute(["echo", "hi"], workspace_root="/tmp")


# ---------------------------------------------------------------------------
# Workspace boundary enforcement
# ---------------------------------------------------------------------------


def test_sandbox_read_workspace(manager: SandboxManager, workspace: Path, caps: object) -> None:
    """Sandboxed process can read files inside the workspace."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}; "
            "workspace boundary tests require SUPPORTED filesystem isolation"
        )
    result = manager.execute(["cat", "test.txt"], workspace_root=workspace, allow_network=True)
    assert result.exit_code == 0
    assert "hello" in result.stdout


def test_sandbox_write_workspace(manager: SandboxManager, workspace: Path, caps: object) -> None:
    """Sandboxed process can create files inside the workspace."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    result = manager.execute(
        ["touch", "new_file.txt"], workspace_root=workspace, allow_network=True
    )
    assert result.exit_code == 0
    assert (workspace / "new_file.txt").exists()


def test_sandbox_write_outside_workspace_blocked(
    manager: SandboxManager, workspace: Path, tmp_path: Path, caps: object
) -> None:
    """Sandboxed process must NOT be able to write outside the workspace."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}; "
            "write-outside-workspace test requires SUPPORTED filesystem isolation"
        )
    outside = tmp_path / "outside.txt"
    result = manager.execute(
        ["touch", outside.as_posix()], workspace_root=workspace, allow_network=True
    )
    assert result.exit_code != 0, (
        "Sandbox allowed write to path outside workspace — this is a security violation"
    )
    assert not outside.exists()


def test_sandbox_read_outside_workspace_blocked(
    manager: SandboxManager, workspace: Path, tmp_path: Path, caps: object
) -> None:
    """Sandboxed process must NOT be able to read files outside the workspace."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    outside = tmp_path / "outside_read.txt"
    outside.write_text("secret")
    result = manager.execute(
        ["cat", outside.as_posix()], workspace_root=workspace, allow_network=True
    )
    assert result.exit_code != 0
    assert "secret" not in result.stdout


def test_sandbox_read_etc_passwd(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Sandboxed process must NOT read /etc/passwd."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    result = manager.execute(["cat", "/etc/passwd"], workspace_root=workspace, allow_network=True)
    assert result.exit_code != 0


def test_sandbox_read_etc_hosts(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Sandboxed process must NOT read /etc/hosts."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    result = manager.execute(["cat", "/etc/hosts"], workspace_root=workspace, allow_network=True)
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# .git directory protection
# ---------------------------------------------------------------------------


def test_sandbox_write_git_dir_blocked(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Sandboxed process must NOT write to .git inside the workspace."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}; "
            ".git protection requires SUPPORTED filesystem isolation"
        )
    git_file = workspace / ".git" / "config"
    result = manager.execute(
        ["touch", git_file.as_posix()], workspace_root=workspace, allow_network=True
    )
    assert result.exit_code != 0, (
        "Sandbox allowed write to .git directory — this is a security violation"
    )
    assert not git_file.exists()


def test_sandbox_read_git_dir_blocked(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Sandboxed process must NOT read files inside .git."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    git_file = workspace / ".git" / "config"
    git_file.parent.mkdir(parents=True, exist_ok=True)
    git_file.write_text("dummy git config")

    result = manager.execute(
        ["cat", git_file.as_posix()], workspace_root=workspace, allow_network=True
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Credential protection
# ---------------------------------------------------------------------------


def test_sandbox_read_ssh_blocked(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Sandboxed process must NOT read ~/.ssh credentials."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    home = Path(os.environ.get("HOME", "/tmp"))
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    dummy_key = ssh_dir / "dummy_rsa"
    dummy_key.write_text("secret")
    try:
        result = manager.execute(
            ["cat", dummy_key.as_posix()], workspace_root=workspace, allow_network=True
        )
        assert result.exit_code != 0
    finally:
        dummy_key.unlink(missing_ok=True)


def test_sandbox_read_aws_credentials_blocked(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Sandboxed process must NOT read ~/.aws/credentials."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    home = Path(os.environ.get("HOME", "/tmp"))
    aws_dir = home / ".aws"
    aws_dir.mkdir(parents=True, exist_ok=True)
    dummy_creds = aws_dir / "credentials"
    dummy_creds.write_text("secret")
    try:
        result = manager.execute(
            ["cat", dummy_creds.as_posix()], workspace_root=workspace, allow_network=True
        )
        assert result.exit_code != 0
    finally:
        dummy_creds.unlink(missing_ok=True)


@pytest.mark.parametrize(
    "cred_file",
    [".kube/config", ".npmrc", ".docker/config.json", ".gcp/credentials", ".netrc"],
)
def test_sandbox_read_various_credentials_blocked(
    manager: SandboxManager,
    workspace: Path,
    caps: object,
    cred_file: str,
) -> None:
    """Sandboxed process must NOT read common credential files under HOME."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    home = Path(os.environ.get("HOME", "/tmp"))
    target = home / cred_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret")
    try:
        result = manager.execute(
            ["cat", target.as_posix()], workspace_root=workspace, allow_network=True
        )
        assert result.exit_code != 0
    finally:
        target.unlink(missing_ok=True)


def test_sandbox_read_config_dir_blocked(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Sandboxed process must NOT read files in ~/.config."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    home = Path(os.environ.get("HOME", "/tmp"))
    config_dir = home / ".config"
    config_dir.mkdir(parents=True, exist_ok=True)
    dummy_file = config_dir / "dummy_config.txt"
    dummy_file.write_text("secret")
    try:
        result = manager.execute(
            ["cat", dummy_file.as_posix()], workspace_root=workspace, allow_network=True
        )
        assert result.exit_code != 0
    finally:
        dummy_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Symlink escape
# ---------------------------------------------------------------------------


def test_sandbox_symlink_escape_blocked(
    manager: SandboxManager, workspace: Path, tmp_path: Path, caps: object
) -> None:
    """A symlink inside the workspace pointing outside must not grant access."""
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    outside_file = tmp_path / "outside_secret.txt"
    outside_file.write_text("secret")
    symlink_file = workspace / "escape_link"
    os.symlink(str(outside_file), str(symlink_file))
    try:
        result = manager.execute(
            ["cat", symlink_file.as_posix()], workspace_root=workspace, allow_network=True
        )
        assert result.exit_code != 0
    finally:
        symlink_file.unlink(missing_ok=True)
        outside_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Network isolation
# ---------------------------------------------------------------------------


def test_sandbox_network_outbound_denied(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Outbound network connections must be denied when network_isolation is SUPPORTED."""
    if not _needs_net_isolation(caps):
        pytest.skip(
            f"network_isolation={getattr(caps, 'network_isolation', 'N/A')} on {_SYSTEM}; "
            "outbound network denial requires SUPPORTED network isolation"
        )
    result = manager.execute(
        ["curl", "--connect-timeout", "2", "https://example.com"],
        workspace_root=workspace,
    )
    assert result.exit_code != 0


def test_sandbox_network_denial_localhost(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Localhost ping must be denied when network_isolation is SUPPORTED."""
    if not _needs_net_isolation(caps):
        pytest.skip(
            f"network_isolation={getattr(caps, 'network_isolation', 'N/A')} on {_SYSTEM}"
        )
    args = ["-c", "1"]
    if _SYSTEM == "Darwin":
        args += ["-t", "1"]  # macOS ping uses -t for timeout
    else:
        args += ["-W", "1"]  # Linux ping uses -W for timeout
    result = manager.execute(
        ["ping", *args, "127.0.0.1"],
        workspace_root=workspace,
        timeout=5,
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Environment / secret stripping
# ---------------------------------------------------------------------------


def test_sandbox_environment_clean(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Host environment variables must not leak into the sandbox.

    NOTE: This relies on secret_filtering being SUPPORTED (env is filtered),
    not on filesystem_isolation. We check the capability explicitly.
    """
    if getattr(caps, "secret_filtering", "NOT_AVAILABLE") != "SUPPORTED":
        pytest.skip(
            f"secret_filtering={getattr(caps, 'secret_filtering', 'N/A')} on {_SYSTEM}"
        )
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    os.environ["AWS_ACCESS_KEY_ID"] = "secret123"
    try:
        cmd = [sys.executable, "-c", "import os; print(list(os.environ.keys()))"]
        result = manager.execute(cmd, workspace_root=workspace, allow_network=True)
        assert result.exit_code == 0
        assert "secret123" not in result.stdout
        assert "AWS_ACCESS_KEY_ID" not in result.stdout
    finally:
        del os.environ["AWS_ACCESS_KEY_ID"]


# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


def test_sandbox_command_timeout(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """A command exceeding the timeout must be killed with exit_code -1.

    Note: We use `time.sleep` here specifically to avoid CPU exhaustion (RLIMIT_CPU),
    so we can verify the backend's explicit `process.wait(timeout=...)` handler.
    For CPU-bound timeout limits, see the stress test suite.
    """
    if not _needs_timeout(caps):
        pytest.skip(
            f"timeout={getattr(caps, 'timeout', 'N/A')} on {_SYSTEM}"
        )
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    result = manager.execute(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        workspace_root=workspace,
        timeout=2,
    )
    assert result.exit_code == -1, (
        f"Expected exit_code -1 for timed-out command, got {result.exit_code}"
    )
    assert "timed out" in result.stderr.lower(), (
        f"Expected 'timed out' in stderr, got: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Output limits
# ---------------------------------------------------------------------------


def test_sandbox_stdout_limit(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """stdout must be truncated when output exceeds the configured limit."""
    if not _needs_output_limit(caps):
        pytest.skip(
            f"output_limit={getattr(caps, 'output_limit', 'N/A')} on {_SYSTEM}"
        )
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    # Produce 60 000 bytes of output — above the 50 000-byte limit
    cmd = [sys.executable, "-c", "print('x' * 60000)"]
    result = manager.execute(cmd, workspace_root=workspace, allow_network=True)
    assert result.exit_code == 0
    assert len(result.stdout) < 60000, "stdout was not truncated"
    assert "TRUNCATED" in result.stdout, (
        "Expected [TRUNCATED:…] marker in truncated stdout"
    )


def test_sandbox_stderr_limit(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """stderr must be truncated when output exceeds the configured limit."""
    if not _needs_output_limit(caps):
        pytest.skip(
            f"output_limit={getattr(caps, 'output_limit', 'N/A')} on {_SYSTEM}"
        )
    if not _needs_fs_isolation(caps):
        pytest.skip(
            f"filesystem_isolation={getattr(caps, 'filesystem_isolation', 'N/A')} on {_SYSTEM}"
        )
    cmd = [sys.executable, "-c", "import sys; sys.stderr.write('x' * 60000)"]
    result = manager.execute(cmd, workspace_root=workspace, allow_network=True)
    assert result.exit_code == 0
    assert len(result.stderr) < 60000, "stderr was not truncated"
    assert "TRUNCATED" in result.stderr, (
        "Expected [TRUNCATED:…] marker in truncated stderr"
    )


# ---------------------------------------------------------------------------
# Child-process / runaway cleanup
# ---------------------------------------------------------------------------


def test_sandbox_child_process_cleanup(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Runaway child processes must be reaped when the parent times out.

    We spawn a short-lived grandchild with a recognisable unique argument,
    then verify it does not survive after the sandbox kills the parent group.
    This test only asserts cleanup behaviour; it does not validate isolation.
    """
    if not _needs_timeout(caps):
        pytest.skip(
            f"timeout={getattr(caps, 'timeout', 'N/A')} on {_SYSTEM}; "
            "child cleanup requires timeout support"
        )
    if _SYSTEM not in ("Darwin", "Linux"):
        pytest.skip("Child-process cleanup via killpg is only verified on POSIX systems")

    import subprocess
    import time

    # Spawn a child that immediately launches a grandchild sleeping 15 s
    unique_marker = "99988877766655.velix_runaway_marker"
    script = (
        "import subprocess, sys\n"
        f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep({unique_marker})'])\n"
    )
    cmd = [sys.executable, "-c", script]

    manager.execute(cmd, workspace_root=workspace, allow_network=True, timeout=2)
    # Brief pause to let the OS schedule cleanup
    time.sleep(0.5)

    result = subprocess.run(
        ["pgrep", "-f", "[9]9988877766655.velix_runaway_marker"],
        capture_output=True,
    )
    assert result.returncode != 0, (
        "Runaway grandchild process survived sandbox termination — kill-pgid cleanup broken"
    )


# ---------------------------------------------------------------------------
# Windows documentation guard
# ---------------------------------------------------------------------------


def test_windows_filesystem_isolation_is_unsupported_not_silently_skipped() -> None:
    """Verify Windows explicitly reports filesystem_isolation=UNSUPPORTED.

    On Windows we must NOT assume isolation exists merely because tests were
    skipped.  This test asserts the documented limitation is reflected in the
    capability object so callers cannot accidentally rely on it.
    """
    if _SYSTEM != "Windows":
        pytest.skip("Windows-only documentation guard")
    mgr = SandboxManager()
    caps = mgr.get_capabilities()
    assert caps.filesystem_isolation == "UNSUPPORTED", (
        "Windows backend must report filesystem_isolation=UNSUPPORTED. "
        "Do not upgrade to SUPPORTED without implementing AppContainer isolation."
    )
    assert caps.network_isolation == "UNSUPPORTED", (
        "Windows backend must report network_isolation=UNSUPPORTED. "
        "Do not upgrade to SUPPORTED without implementing network isolation."
    )
