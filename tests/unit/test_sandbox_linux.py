import platform
import typing
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from velix_agent.sandbox.backends.linux import LinuxSandboxBackend
from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.policy import SandboxPolicy
from velix_agent.sandbox.result import SandboxError


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
        caps = LinuxSandboxBackend.get_capabilities()
        assert caps.filesystem_isolation == "NOT_AVAILABLE"
        assert caps.network_isolation == "NOT_AVAILABLE"
        assert caps.memory_limit == "NOT_AVAILABLE"


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
    """Real Linux integration test: verify that reading and writing .git worktree file fails or cannot mutate host."""
    git_file = tmp_path / ".git"
    git_file.write_text("gitdir: /secret/path/to/gitdir\n")

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    try:
        # 1. Attempt to read host .git worktree file — masked by /dev/null:
        # cat /dev/null succeeds (exit_code == 0) with completely empty output (0 bytes),
        # never revealing the host gitdir secret.
        read_res = backend.execute(["cat", git_file.as_posix()], policy)
        assert read_res.exit_code == 0, f"Expected read of /dev/null mask to exit 0, got {read_res.exit_code}: {read_res.stderr}"
        assert read_res.stdout == "", f"Expected empty stdout from /dev/null mask, got: {read_res.stdout!r}"
        assert "gitdir: /secret/path/to/gitdir" not in read_res.stdout

        # 2. Attempt to overwrite host .git worktree file — read-only bind must reject writes
        write_res = backend.execute(["sh", "-c", f"echo 'corrupted' > {git_file.as_posix()}"], policy)
        assert write_res.exit_code != 0, f"Expected write to fail, got: {write_res.stdout}"

        # 3. Host file content must remain completely unchanged
        assert git_file.read_text() == "gitdir: /secret/path/to/gitdir\n"
    except Exception as e:
        if "Bubblewrap (bwrap) is required" in str(e):
            pytest.skip("bwrap not installed on this Linux host")
        raise


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific actual execution")
def test_linux_backend_git_missing_isolation_real(tmp_path: Path) -> None:
    """Real Linux integration test: verify that when .git does not exist on host, sandbox cannot create rogue .git."""
    git_dir = tmp_path / ".git"
    assert not git_dir.exists(), "Precondition: .git must not exist"

    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    try:
        # 1. Attempt to create files inside .git — must fail due to mode 0000 tmpfs
        write_res = backend.execute(["touch", (git_dir / "rogue_hook").as_posix()], policy)
        assert write_res.exit_code != 0, f"Expected write to fail, got: {write_res.stdout}"

        # 2. Host workspace must remain unchanged — no host .git directory or files created
        assert not git_dir.exists(), "Host workspace must remain unchanged without a .git directory"
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
    """Verify that bwrap creates mountpoint and masks with tmpfs if .git does not exist."""
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
        assert "--dir" in cmd_args
        dir_idx = cmd_args.index("--dir")
        assert cmd_args[dir_idx + 1] == git_path_str
        assert cmd_args[dir_idx + 2] == "--perms"
        assert cmd_args[dir_idx + 3] == "0000"
        assert cmd_args[dir_idx + 4] == "--tmpfs"
        assert cmd_args[dir_idx + 5] == git_path_str


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
        ro_idx = cmd_args.index("--ro-bind")
        # Ensure /dev/null is bound to the git file
        found_mask = False
        for i in range(len(cmd_args) - 2):
            if cmd_args[i] == "--ro-bind" and cmd_args[i + 1] == "/dev/null" and cmd_args[i + 2] == git_path_str:
                found_mask = True
                break
        assert found_mask, f"Expected '--ro-bind /dev/null {git_path_str}' in bwrap args: {cmd_args}"
