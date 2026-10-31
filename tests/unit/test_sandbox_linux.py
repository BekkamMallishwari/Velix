import contextlib
import os
import platform
import typing
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from velix_agent.sandbox.backends.linux import LinuxSandboxBackend
from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.policy import SandboxPolicy
from velix_agent.sandbox.result import SandboxError, SandboxResult


@pytest.fixture
def _cleanup_zero_mode_dirs(tmp_path: Path) -> typing.Generator[None, None, None]:
    """Restore permissions on 0o000-mode directories inside test-owned tmp_path after test.

    Used by tests that deliberately simulate sentinel cleanup failure (which leaves
    a mode-0000 directory inside the test's tmp_path). Scans only within the test's
    own tmp_path, verifies ownership, does not follow symlinks, and restores mode 0o700
    so pytest can remove its temporary directory without warnings.
    """
    import stat as _stat

    yield
    if not tmp_path.is_dir():
        return

    tmp_path_resolved = tmp_path.resolve()
    for dirpath, dirnames, _ in os.walk(tmp_path, topdown=False, followlinks=False):
        for d in dirnames:
            p = os.path.join(dirpath, d)
            try:
                st = os.stat(p, follow_symlinks=False)
                if (
                    not _stat.S_ISLNK(st.st_mode)
                    and _stat.S_ISDIR(st.st_mode)
                    and _stat.S_IMODE(st.st_mode) == 0o000
                    and st.st_uid == os.getuid()
                ):
                    resolved_p = Path(p).resolve()
                    if resolved_p.is_relative_to(tmp_path_resolved):
                        os.chmod(p, 0o700)
            except OSError:
                pass



@pytest.fixture
def clean_systemd_cache() -> typing.Generator[None, None, None]:
    LinuxSandboxBackend._systemd_supported_cache = None
    LinuxSandboxBackend._unshare_net_supported_cache = None
    LinuxSandboxBackend._bwrap_execution_supported_cache = None
    yield
    LinuxSandboxBackend._systemd_supported_cache = None
    LinuxSandboxBackend._unshare_net_supported_cache = None
    LinuxSandboxBackend._bwrap_execution_supported_cache = None


def test_linux_capabilities_no_bwrap(clean_systemd_cache: typing.Any) -> None:
    with patch("shutil.which", return_value=None):
        assert LinuxSandboxBackend.is_bwrap_installed() is False
        assert LinuxSandboxBackend.is_bwrap_execution_supported() is False
        caps = LinuxSandboxBackend.get_capabilities()
        assert caps.filesystem_isolation == "NOT_AVAILABLE"
        assert caps.network_isolation == "NOT_AVAILABLE"
        assert caps.memory_limit == "NOT_AVAILABLE"


def test_linux_capabilities_bwrap_installed_but_execution_fails(
    clean_systemd_cache: typing.Any,
) -> None:
    """Distinguish binary installed from sandbox execution supported."""
    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("subprocess.run") as mock_run:
        # Simulate bwrap: setting up uid map: Permission denied (exit code 1)
        mock_run.return_value = MagicMock(returncode=1)
        assert LinuxSandboxBackend.is_bwrap_installed() is True
        assert LinuxSandboxBackend.is_bwrap_execution_supported() is False
        caps = LinuxSandboxBackend.get_capabilities()
        assert caps.filesystem_isolation == "NOT_AVAILABLE"
        assert caps.network_isolation == "NOT_AVAILABLE"
        assert caps.memory_limit == "NOT_AVAILABLE"


def test_linux_capabilities_bwrap_installed_but_unshare_net_fails(
    clean_systemd_cache: typing.Any,
) -> None:
    """Verify behavior when basic bwrap succeeds but network namespace unshare fails."""
    def mock_run(cmd: list[str], **kwargs: typing.Any) -> MagicMock:
        if "--unshare-net" in cmd:
            return MagicMock(returncode=1)
        return MagicMock(returncode=0)

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("subprocess.run", side_effect=mock_run):
        assert LinuxSandboxBackend.is_bwrap_installed() is True
        # Basic bwrap execution supported
        assert (
            LinuxSandboxBackend.is_bwrap_execution_supported(require_network_isolation=False)
            is True
        )
        # Full sandbox requirements (including network isolation) fails
        assert (
            LinuxSandboxBackend.is_bwrap_execution_supported(require_network_isolation=True)
            is False
        )
        caps = LinuxSandboxBackend.get_capabilities()
        assert caps.filesystem_isolation == "SUPPORTED"
        assert caps.network_isolation == "UNSUPPORTED"


def test_linux_capabilities_no_systemd(clean_systemd_cache: typing.Any) -> None:
    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/bwrap" if cmd == "bwrap" else None

    with patch("shutil.which", side_effect=mock_which), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        caps = LinuxSandboxBackend.get_capabilities()
        assert caps.filesystem_isolation == "SUPPORTED"
        assert caps.network_isolation == "SUPPORTED"
        assert caps.memory_limit == "PARTIALLY_SUPPORTED"
        assert caps.process_limit == "PARTIALLY_SUPPORTED"
        assert caps.cpu_limit == "PARTIALLY_SUPPORTED"


def test_linux_capabilities_with_systemd(clean_systemd_cache: typing.Any) -> None:
    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/bwrap" if cmd == "bwrap" else "/usr/bin/systemd-run"

    with patch("shutil.which", side_effect=mock_which), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        caps = LinuxSandboxBackend.get_capabilities()
        assert caps.filesystem_isolation == "SUPPORTED"
        assert caps.memory_limit == "SUPPORTED"
        assert caps.process_limit == "SUPPORTED"

        # Verify that systemd-run probe included --no-ask-password and a timeout guard
        systemd_calls = [
            c for c in mock_run.call_args_list if c[0][0][0] == "systemd-run"
        ]
        assert len(systemd_calls) == 1
        cmd_args = systemd_calls[0][0][0]
        assert "--no-ask-password" in cmd_args
        assert systemd_calls[0][1].get("timeout") is not None
        assert systemd_calls[0][1]["timeout"] <= 5


def test_linux_capabilities_systemd_probe_timeout(clean_systemd_cache: typing.Any) -> None:
    """Verify that if systemd-run probe times out, detection fails closed without raising."""
    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/bwrap" if cmd == "bwrap" else "/usr/bin/systemd-run"

    import subprocess

    def mock_run(cmd: list[str], *args: typing.Any, **kwargs: typing.Any) -> MagicMock:
        if cmd[0] == "systemd-run":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 2))
        return MagicMock(returncode=0)

    with patch("shutil.which", side_effect=mock_which), \
         patch("subprocess.run", side_effect=mock_run):
        caps = LinuxSandboxBackend.get_capabilities()
        assert caps.memory_limit == "PARTIALLY_SUPPORTED"
        assert caps.process_limit == "PARTIALLY_SUPPORTED"


def test_linux_capabilities_systemd_probe_oserror(clean_systemd_cache: typing.Any) -> None:
    """Verify that if systemd probe fails with OSError, detection fails closed without raising."""
    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/bwrap" if cmd == "bwrap" else "/usr/bin/systemd-run"

    def mock_run(cmd: list[str], *args: typing.Any, **kwargs: typing.Any) -> MagicMock:
        if cmd[0] == "systemd-run":
            raise OSError("systemd-run binary execution failed")
        return MagicMock(returncode=0)

    with patch("shutil.which", side_effect=mock_which), \
         patch("subprocess.run", side_effect=mock_run):
        caps = LinuxSandboxBackend.get_capabilities()
        assert caps.memory_limit == "PARTIALLY_SUPPORTED"
        assert caps.process_limit == "PARTIALLY_SUPPORTED"
        assert LinuxSandboxBackend._systemd_supported_cache is False


def test_linux_capabilities_systemd_probe_exit_nonzero(clean_systemd_cache: typing.Any) -> None:
    """Verify that if systemd probe exits non-zero, detection fails closed without raising."""
    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/bwrap" if cmd == "bwrap" else "/usr/bin/systemd-run"

    def mock_run(cmd: list[str], *args: typing.Any, **kwargs: typing.Any) -> MagicMock:
        if cmd[0] == "systemd-run":
            return MagicMock(returncode=1)
        return MagicMock(returncode=0)

    with patch("shutil.which", side_effect=mock_which), \
         patch("subprocess.run", side_effect=mock_run):
        caps = LinuxSandboxBackend.get_capabilities()
        assert caps.memory_limit == "PARTIALLY_SUPPORTED"
        assert caps.process_limit == "PARTIALLY_SUPPORTED"
        assert LinuxSandboxBackend._systemd_supported_cache is False


def test_manager_strict_mode_rejects_partial(
    clean_systemd_cache: typing.Any, tmp_path: Path
) -> None:
    # On macOS or Linux where systemd-run is missing, backend returns PARTIALLY_SUPPORTED
    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/bwrap" if cmd == "bwrap" else None

    with patch("shutil.which", side_effect=mock_which), \
         patch("subprocess.run") as mock_run, \
         patch("platform.system", return_value="Linux"):
        mock_run.return_value = MagicMock(returncode=0)
        manager = SandboxManager()
        with pytest.raises(SandboxError, match="PARTIALLY_SUPPORTED"):
            manager.execute(
                ["echo", "test"],
                workspace_root=tmp_path,
                mode="STRICT",
                memory_limit=1024,
            )


def test_manager_balanced_mode_accepts_partial(
    clean_systemd_cache: typing.Any, tmp_path: Path
) -> None:
    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/bwrap" if cmd == "bwrap" else None

    with patch("shutil.which", side_effect=mock_which), \
         patch("subprocess.run") as mock_run, \
         patch("platform.system", return_value="Linux"), \
         patch("velix_agent.sandbox.backends.linux.LinuxSandboxBackend.execute") as mock_exec, \
         patch("velix_agent.core.logging.get_logger") as mock_logger:

        mock_run.return_value = MagicMock(returncode=0)
        mock_exec.return_value = MagicMock(stdout="", stderr="", exit_code=0, command=[])

        manager = SandboxManager()
        manager.execute(
            ["echo", "test"],
            workspace_root=tmp_path,
            mode="BALANCED",
            memory_limit=1024,
        )
        # Should have warned about PARTIALLY_SUPPORTED
        assert mock_logger.return_value.warning.called


def test_linux_default_execution_reaches_backend_in_strict_mode(
    clean_systemd_cache: typing.Any, tmp_path: Path
) -> None:
    """Verify that default execution reaches backend execution on Linux in STRICT mode.

    Because cpu_limit defaults to False, the fact that Linux reports cpu_limit as
    PARTIALLY_SUPPORTED does not block default strict-mode execution when other
    required capabilities (filesystem, network, timeout, output_limit, secret_filtering)
    are SUPPORTED.
    """
    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/bwrap" if cmd == "bwrap" else None

    with patch("shutil.which", side_effect=mock_which), \
         patch("subprocess.run") as mock_run, \
         patch("platform.system", return_value="Linux"), \
         patch.object(LinuxSandboxBackend, "_detect_bwrap_execution", return_value=True), \
         patch.object(LinuxSandboxBackend, "_detect_unshare_net", return_value=True), \
         patch.object(LinuxSandboxBackend, "execute") as mock_backend_execute:

        mock_run.return_value = MagicMock(returncode=0)
        mock_backend_execute.return_value = SandboxResult(
            stdout="linux default ok", stderr="", exit_code=0, command=["echo"]
        )

        manager = SandboxManager()
        caps = manager.get_capabilities()
        assert caps.cpu_limit == "PARTIALLY_SUPPORTED"
        assert caps.filesystem_isolation == "SUPPORTED"
        assert caps.network_isolation == "SUPPORTED"
        assert caps.timeout == "SUPPORTED"
        assert caps.output_limit == "SUPPORTED"

        # Default execution with mode="STRICT" (and no explicit cpu_limit) must reach the backend
        res = manager.execute(
            ["echo", "hello"],
            workspace_root=tmp_path,
            mode="STRICT",
        )
        assert res.exit_code == 0
        assert mock_backend_execute.called
        policy_used = mock_backend_execute.call_args[0][1]
        assert policy_used.cpu_limit is False

        # If caller explicitly requests cpu_limit=True in STRICT mode, it must fail closed
        match_msg = (
            r"Capability 'cpu_limit' is required in STRICT mode but is only PARTIALLY_SUPPORTED\."
        )
        with pytest.raises(SandboxError, match=match_msg):
            manager.execute(
                ["echo", "hello"],
                workspace_root=tmp_path,
                mode="STRICT",
                cpu_limit=True,
            )



@pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific actual execution")
def test_linux_backend_execution(tmp_path: Path) -> None:
    backend = LinuxSandboxBackend()
    caps = backend.get_capabilities()
    if caps.network_isolation != "SUPPORTED":
        pytest.skip(
            "Environment does not permit unprivileged network namespaces "
            "(bwrap --unshare-net)"
        )

    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=False)

    try:
        result = backend.execute(["echo", "linux"], policy)
        assert result.exit_code == 0
        assert "linux" in result.stdout
    except Exception as e:
        if "Bubblewrap (bwrap) is required" in str(e):
            pytest.skip("bwrap not installed on this Linux host")
        raise


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific actual execution")
def test_linux_backend_git_directory_isolation_real(tmp_path: Path) -> None:
    """Real Linux integration test: verify that reading and writing .git directory fails."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    config_file = git_dir / "config"
    config_file.write_text("secret_git_config_content\n")

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    try:
        # 1. Attempt to read host .git/config — must fail (nonzero exit code)
        read_res = backend.execute(["cat", (git_dir / "config").as_posix()], policy)
        assert read_res.exit_code != 0, f"Expected read to fail, got: {read_res.stdout}"
        assert "secret_git_config_content" not in read_res.stdout

        # 2. Attempt to write or overwrite host .git/config — must fail (nonzero exit code)
        write_res = backend.execute(["touch", (git_dir / "config").as_posix()], policy)
        assert write_res.exit_code != 0, f"Expected write to fail, got: {write_res.stdout}"

        # 3. Host file content must remain completely unchanged
        assert config_file.read_text() == "secret_git_config_content\n"
    except Exception as e:
        if "Bubblewrap (bwrap) is required" in str(e):
            pytest.skip("bwrap not installed on this Linux host")
        raise


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific actual execution")
def test_linux_backend_git_worktree_file_isolation_real(tmp_path: Path) -> None:
    """Real Linux integration test: verify that reading and writing .git worktree file fails."""
    git_file = tmp_path / ".git"
    git_file.write_text("gitdir: /secret/path/to/gitdir\n")

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    try:
        # 1. Attempt to read host .git worktree file — masked by /dev/null:
        # Secret content must never be exposed.
        read_res = backend.execute(["cat", git_file.as_posix()], policy)
        assert "gitdir: /secret/path/to/gitdir" not in read_res.stdout

        # 2. Attempt to overwrite host .git worktree file — read-only bind must reject writes
        cmd = ["sh", "-c", f"echo 'corrupted' > {git_file.as_posix()}"]
        write_res = backend.execute(cmd, policy)
        assert write_res.exit_code != 0, f"Expected write to fail, got: {write_res.stdout}"

        # 3. Host file content must remain completely unchanged
        assert git_file.read_text() == "gitdir: /secret/path/to/gitdir\n"
    except Exception as e:
        if "Bubblewrap (bwrap) is required" in str(e):
            pytest.skip("bwrap not installed on this Linux host")
        raise


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific actual execution")
def test_linux_backend_git_missing_isolation_real(tmp_path: Path) -> None:
    """Real Linux integration test: verify sandbox cannot create rogue .git on host."""
    git_dir = tmp_path / ".git"
    assert not git_dir.exists(), "Precondition: .git must not exist"

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    try:
        # 1. Ordinary command execution: leaves host workspace clean without .git
        res = backend.execute(["echo", "hello"], policy)
        assert res.exit_code == 0
        assert "hello" in res.stdout
        assert not git_dir.exists(), "Host workspace must remain without .git after normal command"

        # 2. Legitimate workspace write succeeds and persists on host
        legit_file = tmp_path / "legit_test.txt"
        res_legit = backend.execute(["touch", legit_file.as_posix()], policy)
        assert res_legit.exit_code == 0
        assert legit_file.is_file(), "Legitimate workspace writes must succeed"

        # 3. Attempting to create .git directory from inside sandbox must fail
        res_mkdir = backend.execute(["mkdir", git_dir.as_posix()], policy)
        assert res_mkdir.exit_code != 0, f"Expected mkdir to fail, got {res_mkdir.exit_code}"
        assert not git_dir.exists(), "Host workspace must remain without .git"

        # 4. Attempting to plant git hooks from inside sandbox must fail
        hook_path = (git_dir / "hooks" / "pre-commit").as_posix()
        res_hook = backend.execute(["touch", hook_path], policy)
        assert res_hook.exit_code != 0, f"Expected hook fail, got {res_hook.exit_code}"
        assert not git_dir.exists(), "Host workspace must remain without .git"
    except Exception as e:
        if "Bubblewrap (bwrap) is required" in str(e):
            pytest.skip("bwrap not installed on this Linux host")
        raise


def test_bwrap_command_masks_git_directory_existing(tmp_path: Path) -> None:
    """Verify that bwrap mounts a restricted tmpfs (perms 0000) over existing .git."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("dummy")

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch("subprocess.Popen") as mock_popen:

        import io

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.stdout = io.BytesIO(b"")
        mock_proc.stderr = io.BytesIO(b"")
        mock_popen.return_value = mock_proc

        backend.execute(["echo", "test"], policy)

        assert mock_popen.called
        cmd_args = mock_popen.call_args[0][0]

        git_path_str = git_dir.as_posix()
        # Verify --perms 0000 and --tmpfs git_path are present in order
        assert "--perms" in cmd_args
        perms_idx = cmd_args.index("--perms")
        assert cmd_args[perms_idx + 1] == "0000"
        assert cmd_args[perms_idx + 2] == "--tmpfs"
        assert cmd_args[perms_idx + 3] == git_path_str


def test_bwrap_command_masks_git_directory_nonexistent(tmp_path: Path) -> None:
    """Verify that bwrap uses a transient sentinel to mask nonexistent .git with tmpfs mode 0000."""
    git_dir = tmp_path / ".git"
    assert not git_dir.exists()

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch("subprocess.Popen") as mock_popen:

        import io

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.stdout = io.BytesIO(b"")
        mock_proc.stderr = io.BytesIO(b"")
        mock_popen.return_value = mock_proc

        backend.execute(["echo", "test"], policy)

        assert mock_popen.called
        cmd_args = mock_popen.call_args[0][0]

        git_path_str = git_dir.as_posix()
        # Verify --perms 0000 and --tmpfs git_path are present in order
        assert "--perms" in cmd_args
        perms_idx = cmd_args.index("--perms")
        assert cmd_args[perms_idx + 1] == "0000"
        assert cmd_args[perms_idx + 2] == "--tmpfs"
        assert cmd_args[perms_idx + 3] == git_path_str
        # Verify --dir is NOT passed to bwrap (no setup-time host directory creation by bwrap)
        assert "--dir" not in cmd_args

        # Verify host workspace remains clean after execute() returns
        assert not git_dir.exists()


def test_bwrap_command_masks_git_worktree_file(tmp_path: Path) -> None:
    """Verify that bwrap masks .git worktree regular file using --perms 0000 --ro-bind /dev/null."""
    git_file = tmp_path / ".git"
    git_file.write_text("gitdir: /path/to/main/repo/.git/worktrees/branch\n")
    assert git_file.is_file()

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch("subprocess.Popen") as mock_popen:

        import io

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.stdout = io.BytesIO(b"")
        mock_proc.stderr = io.BytesIO(b"")
        mock_popen.return_value = mock_proc

        backend.execute(["echo", "test"], policy)

        assert mock_popen.called
        cmd_args = mock_popen.call_args[0][0]

        git_path_str = git_file.as_posix()
        assert "--ro-bind" in cmd_args
        # Ensure /dev/null is bound to the git file
        found_mask = any(
            cmd_args[i] == "--ro-bind"
            and cmd_args[i + 1] == "/dev/null"
            and cmd_args[i + 2] == git_path_str
            for i in range(len(cmd_args) - 2)
        )
        assert found_mask, f"Expected '--ro-bind /dev/null {git_path_str}' in: {cmd_args}"


def test_bwrap_sentinel_replacement_protection(tmp_path: Path) -> None:
    """Verify that if sentinel is replaced, cleanup refuses delete and raises SandboxError."""
    git_dir = tmp_path / ".git"
    assert not git_dir.exists()

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch("subprocess.Popen") as mock_popen:

        import io

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.stdout = io.BytesIO(b"")
        mock_proc.stderr = io.BytesIO(b"")

        # Simulate external entity replacing the sentinel while bwrap is running
        def fake_popen(*args: typing.Any, **kwargs: typing.Any) -> MagicMock:
            # External process removes the sentinel and replaces it with a new real directory/file
            os.rmdir(git_dir)
            # Recreate with different inode / content
            git_dir.mkdir()
            (git_dir / "real_repo_config").write_text("keep_me")
            return mock_proc

        mock_popen.side_effect = fake_popen

        # Cleanup must detect identity mismatch, refuse to delete, and raise observable SandboxError
        with pytest.raises(SandboxError, match=r"Sentinel at .* was replaced or has mismatched"):
            backend.execute(["echo", "test"], policy)

        # Path must be left untouched
        assert git_dir.exists(), "Replaced directory must not be deleted by sentinel cleanup"
        assert (git_dir / "real_repo_config").exists()


def test_bwrap_sentinel_concurrent_refcounting(tmp_path: Path) -> None:
    """Verify concurrent sandbox executions on same workspace coordinate sentinel cleanly."""
    git_dir = tmp_path / ".git"
    assert not git_dir.exists()

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch("subprocess.Popen") as mock_popen:

        import io

        mock_proc1 = MagicMock()
        mock_proc1.poll.return_value = 0
        mock_proc1.returncode = 0
        mock_proc1.stdout = io.BytesIO(b"")
        mock_proc1.stderr = io.BytesIO(b"")

        mock_proc2 = MagicMock()
        mock_proc2.poll.return_value = 0
        mock_proc2.returncode = 0
        mock_proc2.stdout = io.BytesIO(b"")
        mock_proc2.stderr = io.BytesIO(b"")

        # While call 1 is "running", run call 2
        def run_concurrent(*args: typing.Any, **kwargs: typing.Any) -> MagicMock:
            # During execution of call 1, run call 2
            mock_popen.side_effect = None
            mock_popen.return_value = mock_proc2
            res2 = backend.execute(["echo", "concurrent"], policy)
            assert res2.exit_code == 0
            # During call 1, the sentinel must still exist
            assert git_dir.exists(), "Sentinel must not be removed while call 1 is still active"
            return mock_proc1

        mock_popen.side_effect = run_concurrent

        res1 = backend.execute(["echo", "first"], policy)
        assert res1.exit_code == 0

        # After both complete, sentinel should be cleaned up
        assert not git_dir.exists(), "Sentinel must be cleaned up after all executions finish"


@pytest.mark.timeout(30)
def test_bwrap_sentinel_real_multithread_concurrency(tmp_path: Path) -> None:
    """Verify genuinely concurrent threads executing on the same workspace coordinate safely."""
    git_dir = tmp_path / ".git"
    assert not git_dir.exists()

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/bwrap" if cmd == "bwrap" else None

    with patch("shutil.which", side_effect=mock_which), \
         patch("platform.system", return_value="Linux"), \
         patch("subprocess.Popen") as mock_popen:

        import io
        import time

        def slow_popen(*args: typing.Any, **kwargs: typing.Any) -> MagicMock:
            time.sleep(0.02)
            mock_proc = MagicMock()
            mock_proc.poll.return_value = 0
            mock_proc.returncode = 0
            mock_proc.stdout = io.BytesIO(b"")
            mock_proc.stderr = io.BytesIO(b"")
            return mock_proc

        mock_popen.side_effect = slow_popen

        import concurrent.futures

        def worker(idx: int) -> int:
            res = backend.execute(["echo", f"thread-{idx}"], policy)
            return res.exit_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker, i) for i in range(4)]
            results = [f.result(timeout=10) for f in futures]

        assert all(code == 0 for code in results)
        assert not git_dir.exists(), "Sentinel must be completely cleaned up after threads finish"


def _mp_worker(ws_str: str, out_queue: typing.Any) -> None:
    import io
    import time
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    from velix_agent.sandbox.backends.linux import LinuxSandboxBackend
    from velix_agent.sandbox.policy import SandboxPolicy

    ws = Path(ws_str)
    b = LinuxSandboxBackend()
    pol = SandboxPolicy(workspace_root=ws, allow_network=True)

    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/bwrap" if cmd == "bwrap" else None

    with patch("shutil.which", side_effect=mock_which), \
         patch("platform.system", return_value="Linux"), \
         patch("subprocess.Popen") as mp_popen:

        def slow_p(*args: typing.Any, **kwargs: typing.Any) -> MagicMock:
            time.sleep(0.05)
            p = MagicMock()
            p.poll.return_value = 0
            p.returncode = 0
            p.stdout = io.BytesIO(b"")
            p.stderr = io.BytesIO(b"")
            return p

        mp_popen.side_effect = slow_p
        res = b.execute(["echo", "mp"], pol)
        out_queue.put(res.exit_code)


@pytest.mark.timeout(30)
def test_bwrap_sentinel_multiprocess_concurrency(tmp_path: Path) -> None:
    """Verify genuinely independent processes coordinate sentinel via client token IPC locking.

    A 30-second hard timeout is applied via pytest-timeout to guarantee that a stuck
    spawned worker process cannot block the CI runner indefinitely.
    """
    import multiprocessing

    git_dir = tmp_path / ".git"
    assert not git_dir.exists()

    ctx = multiprocessing.get_context("spawn")
    q: typing.Any = ctx.Queue()
    p1 = ctx.Process(target=_mp_worker, args=(tmp_path.as_posix(), q))
    p2 = ctx.Process(target=_mp_worker, args=(tmp_path.as_posix(), q))

    processes = [p1, p2]
    try:
        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)

        assert not p1.is_alive(), "Worker process 1 timed out"
        assert not p2.is_alive(), "Worker process 2 timed out"

        res1 = q.get(timeout=5)
        res2 = q.get(timeout=5)

        assert res1 == 0
        assert res2 == 0
        assert not git_dir.exists(), "Sentinel must be removed after all processes finish"
    finally:
        for p in processes:
            # 1. Attempt graceful termination
            try:
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=1)
            except Exception:
                pass

            # 2. Force kill if worker remains alive (even if terminate raised)
            try:
                if p.is_alive():
                    p.kill()
                    p.join(timeout=1)
            except Exception:
                pass

            # 3. Clean up process descriptor resources
            with contextlib.suppress(Exception):
                p.close()
        with contextlib.suppress(Exception):
            # cancel_join_thread MUST be called before close() on Linux.
            # q.close() blocks until the Queue's background feeder thread finishes
            # flushing its write buffer; cancel_join_thread() skips that wait.
            # Calling cancel_join_thread() first prevents a deadlock when the
            # spawned worker process exited without draining the queue.
            q.cancel_join_thread()
        with contextlib.suppress(Exception):
            q.close()


def test_bwrap_lock_acquisition_failure_fails_closed(tmp_path: Path) -> None:
    """Verify that if workspace lock acquisition fails, backend fails closed with SandboxError."""
    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch("fcntl.flock", side_effect=OSError("Lock acquisition failed")):

        err_pattern = r"Failed to acquire (workspace master|execution client token)"
        with pytest.raises(SandboxError, match=err_pattern):
            backend.execute(["echo", "test"], policy)

        # Precondition verified: no .git or sentinel directory was created
        assert not (tmp_path / ".git").exists()


def test_bwrap_lock_acquisition_contention_timeout_fails_closed(tmp_path: Path) -> None:
    """Verify that lock contention retries until timeout, closes fd, and fails closed."""
    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    current_time = 0.0

    def advancing_monotonic() -> float:
        nonlocal current_time
        val = current_time
        current_time += 6.0
        return val

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch("fcntl.flock", side_effect=BlockingIOError("Resource temporarily unavailable")), \
         patch("time.sleep"), \
         patch("time.monotonic", side_effect=advancing_monotonic):

        err_pattern = r"Failed to acquire workspace master lock.*timed out after 10s"
        with pytest.raises(SandboxError, match=err_pattern):
            backend.execute(["echo", "test"], policy)

        assert not (tmp_path / ".git").exists()


def test_bwrap_timeout_preserves_sentinel_cleanup(tmp_path: Path) -> None:
    """Verify that when command times out, sentinel is cleanly cleaned up."""
    git_dir = tmp_path / ".git"
    assert not git_dir.exists()

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch("subprocess.Popen") as mock_popen:

        import io
        import subprocess

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd=["sleep", "10"], timeout=1),
            0,
        ]
        mock_proc.stdout = io.BytesIO(b"")
        mock_proc.stderr = io.BytesIO(b"")
        mock_popen.return_value = mock_proc

        res = backend.execute(["sleep", "10"], policy, timeout=1)
        assert res.exit_code == -1
        assert "timed out" in res.stderr
        assert not git_dir.exists(), "Sentinel must be removed even if command timed out"


def test_bwrap_execution_and_cleanup_failure_chains_exception(
    tmp_path: Path, _cleanup_zero_mode_dirs: typing.Any
) -> None:
    """Verify that if execution fails and cleanup also fails, original exception is chained."""
    git_dir = tmp_path / ".git"
    assert not git_dir.exists()

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch("subprocess.Popen") as mock_popen:

        # Command fails with OSError during Popen
        mock_popen.side_effect = OSError("Subprocess launch failed")

        with patch("os.rmdir", side_effect=OSError("rmdir failed")):
            with pytest.raises(SandboxError) as exc_info:
                backend.execute(["fail"], policy)

            # Both cleanup failure and original execution error must be visible
            assert "original execution error" in str(exc_info.value)
            assert exc_info.value.__cause__ is not None


def test_bwrap_systemd_scope_cleanup_timeout_suppressed(
    clean_systemd_cache: typing.Any, tmp_path: Path
) -> None:
    """Verify both cleanup commands are attempted with safeguards even when kill times out."""
    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, memory_limit=1024, allow_network=True)

    import io
    import subprocess

    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_proc.returncode = 0
    mock_proc.stdout = io.BytesIO(b"ok\n")
    mock_proc.stderr = io.BytesIO(b"")

    systemctl_calls: list[list[str]] = []
    systemctl_kwargs: list[dict[str, typing.Any]] = []

    def mock_run(cmd: list[str], *args: typing.Any, **kwargs: typing.Any) -> MagicMock:
        if cmd[0] == "systemctl":
            systemctl_calls.append(cmd)
            systemctl_kwargs.append(kwargs)
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 5))
        return MagicMock(returncode=0)

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch.object(LinuxSandboxBackend, "_detect_systemd", return_value=True), \
         patch("subprocess.Popen", return_value=mock_proc), \
         patch("subprocess.run", side_effect=mock_run):

        res = backend.execute(["echo", "ok"], policy)
        assert res.exit_code == 0
        assert "ok" in res.stdout

        # Verify both kill and stop are attempted even when kill times out
        assert len(systemctl_calls) == 2

        # Verify systemctl kill invocation and safeguards
        kill_cmd = systemctl_calls[0]
        assert kill_cmd[0] == "systemctl"
        assert "kill" in kill_cmd
        assert "--kill-who=all" in kill_cmd
        assert "--signal=SIGKILL" in kill_cmd
        assert "--no-ask-password" in kill_cmd
        assert systemctl_kwargs[0].get("timeout") == 5

        # Verify systemctl stop invocation and safeguards
        stop_cmd = systemctl_calls[1]
        assert stop_cmd[0] == "systemctl"
        assert "stop" in stop_cmd
        assert "--no-ask-password" in stop_cmd
        assert systemctl_kwargs[1].get("timeout") == 5


# ---------------------------------------------------------------------------
# Linux SandboxManager integration & hardening tests
# ---------------------------------------------------------------------------


def test_manager_linux_missing_bwrap_fails_closed(
    clean_systemd_cache: typing.Any, tmp_path: Path
) -> None:
    """Manager on Linux fails closed in STRICT mode when bwrap is not installed."""
    with patch("shutil.which", return_value=None), \
         patch("platform.system", return_value="Linux"):
        manager = SandboxManager()
        assert isinstance(manager.backend, LinuxSandboxBackend)

        caps = manager.get_capabilities()
        assert caps.filesystem_isolation == "NOT_AVAILABLE"

        err_match = (
            r"Capability 'filesystem_isolation' is required in STRICT mode but is NOT_AVAILABLE"
        )
        with pytest.raises(SandboxError, match=err_match):
            manager.execute(["echo", "blocked"], workspace_root=tmp_path, mode="STRICT")


def test_manager_linux_unavailable_netns_fails_closed_when_network_disallowed(
    clean_systemd_cache: typing.Any, tmp_path: Path
) -> None:
    """When network namespaces are unavailable, disallowing network must fail closed."""
    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/bwrap" if cmd == "bwrap" else None

    with patch("shutil.which", side_effect=mock_which), \
         patch("platform.system", return_value="Linux"), \
         patch.object(LinuxSandboxBackend, "_detect_bwrap_execution", return_value=True), \
         patch.object(LinuxSandboxBackend, "_detect_unshare_net", return_value=False):

        manager = SandboxManager()
        caps = manager.get_capabilities()
        assert caps.filesystem_isolation == "SUPPORTED"
        assert caps.network_isolation == "UNSUPPORTED"

        # STRICT mode with allow_network=False requires network_isolation -> fails closed
        strict_err = (
            r"Capability 'network_isolation' is required in STRICT mode but is UNSUPPORTED"
        )
        with pytest.raises(SandboxError, match=strict_err):
            manager.execute(
                ["echo", "net"], workspace_root=tmp_path, mode="STRICT", allow_network=False
            )

        # BALANCED mode with allow_network=False also requires network_isolation -> fails closed
        balanced_err = (
            r"Capability 'network_isolation' is required in BALANCED mode but is UNSUPPORTED"
        )
        with pytest.raises(SandboxError, match=balanced_err):
            manager.execute(
                ["echo", "net"], workspace_root=tmp_path, mode="BALANCED", allow_network=False
            )


def test_manager_linux_supported_execution_with_secrets_and_truncation(
    clean_systemd_cache: typing.Any, tmp_path: Path
) -> None:
    """Verify Linux execution through SandboxManager preserves secrets redaction and truncation."""
    from velix_agent.sandbox.result import OUTPUT_TRUNCATION_MARKER

    secret_val = "linux_super_secret_tok"

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch.object(LinuxSandboxBackend, "_detect_bwrap_execution", return_value=True), \
         patch.object(LinuxSandboxBackend, "_detect_unshare_net", return_value=True), \
         patch.object(LinuxSandboxBackend, "execute") as mock_exec:

        mock_exec.return_value = SandboxResult(
            stdout=f"Output with {secret_val} tail" + OUTPUT_TRUNCATION_MARKER,
            stderr=f"Err {secret_val}",
            exit_code=0,
            command=["echo", secret_val],
            truncation_status={"stdout": True, "stderr": False},
        )

        manager = SandboxManager()
        res = manager.execute(
            ["echo", secret_val],
            workspace_root=tmp_path,
            mode="STRICT",
            secrets={"MY_SECRET": secret_val},
        )

        assert secret_val not in res.stdout
        assert secret_val not in res.stderr
        assert secret_val not in res.command[1]
        assert "***REDACTED***" in res.stdout
        assert "***REDACTED***" in res.stderr
        assert "***REDACTED***" in res.command[1]
        assert OUTPUT_TRUNCATION_MARKER in res.stdout


def test_manager_linux_workspace_root_validation_preserved(
    clean_systemd_cache: typing.Any
) -> None:
    """Linux execution preserves workspace root validation (rejects / and home)."""
    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch.object(LinuxSandboxBackend, "_detect_bwrap_execution", return_value=True), \
         patch.object(LinuxSandboxBackend, "_detect_unshare_net", return_value=True):

        manager = SandboxManager()

        # Filesystem root must be rejected
        with pytest.raises(SandboxError, match="filesystem root is not allowed"):
            manager.execute(["echo", "root"], workspace_root="/")

        # User home directory must be rejected
        with pytest.raises(SandboxError, match="user home directory is not allowed"):
            manager.execute(["echo", "home"], workspace_root=Path.home())


def test_linux_backend_process_group_termination_on_timeout(tmp_path: Path) -> None:
    """Verify backend sends SIGKILL to process group on timeout."""
    import io
    import signal
    import subprocess

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    mock_proc = MagicMock()
    mock_proc.pid = 99999
    mock_proc.poll.return_value = None
    mock_proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd=["sleep", "60"], timeout=1),
        0,
    ]
    mock_proc.stdout = io.BytesIO(b"")
    mock_proc.stderr = io.BytesIO(b"")

    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("platform.system", return_value="Linux"), \
         patch("subprocess.Popen", return_value=mock_proc), \
         patch("os.killpg") as mock_killpg:

        res = backend.execute(["sleep", "60"], policy, timeout=1)

        assert res.exit_code == -1
        assert "timed out" in res.stderr
        mock_killpg.assert_called_once_with(99999, signal.SIGKILL)
