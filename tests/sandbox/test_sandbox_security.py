import os
import platform
from pathlib import Path

import pytest

from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.result import SandboxError


@pytest.fixture
def workspace(tmp_path):
    # Setup dummy workspace
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    (workspace / "test.txt").write_text("hello")
    return workspace


@pytest.fixture
def manager():
    return SandboxManager()


def test_sandbox_read_workspace(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    result = manager.execute(["cat", "test.txt"], workspace_root=workspace)
    assert result.exit_code == 0
    assert "hello" in result.stdout


def test_sandbox_write_workspace(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    result = manager.execute(["touch", "new_file.txt"], workspace_root=workspace)
    assert result.exit_code == 0
    assert (workspace / "new_file.txt").exists()


def test_sandbox_write_outside_workspace(manager, workspace, tmp_path):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    outside = tmp_path / "outside.txt"
    result = manager.execute(["touch", outside.as_posix()], workspace_root=workspace)

    # Should fail (Seatbelt usually returns 1 or permission denied)
    assert result.exit_code != 0
    assert not outside.exists()


def test_sandbox_read_ssh(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    ssh_dir = Path(os.environ.get("HOME", "/tmp")) / ".ssh"
    if not ssh_dir.exists():
        ssh_dir.mkdir(parents=True, exist_ok=True)

    dummy_key = ssh_dir / "dummy_rsa"
    dummy_key.write_text("secret")

    result = manager.execute(["cat", dummy_key.as_posix()], workspace_root=workspace)
    assert result.exit_code != 0

    # cleanup
    dummy_key.unlink()


def test_sandbox_write_git_dir(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    git_file = workspace / ".git" / "config"
    result = manager.execute(["touch", git_file.as_posix()], workspace_root=workspace)

    assert result.exit_code != 0
    assert not git_file.exists()


def test_sandbox_network_disabled(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    # Attempt curl
    result = manager.execute(
        ["curl", "--connect-timeout", "2", "https://example.com"], workspace_root=workspace
    )

    assert result.exit_code != 0


def test_sandbox_environment_clean(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    # We should not see arbitrary env variables like AWS_ACCESS_KEY_ID
    os.environ["AWS_ACCESS_KEY_ID"] = "secret123"
    result = manager.execute(["env"], workspace_root=workspace)

    assert result.exit_code == 0
    assert "secret123" not in result.stdout
    assert "AWS_ACCESS_KEY_ID" not in result.stdout


def test_sandbox_fail_closed():
    # Simulate an unsupported platform by forcing None backend
    manager = SandboxManager(_force_none=True)
    with pytest.raises(SandboxError) as excinfo:
        manager.execute(["ls"], workspace_root="/tmp")
    assert "unavailable" in str(excinfo.value)


def test_sandbox_read_etc_passwd(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    result = manager.execute(["cat", "/etc/passwd"], workspace_root=workspace)
    assert result.exit_code != 0


def test_sandbox_read_etc_hosts(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    result = manager.execute(["cat", "/etc/hosts"], workspace_root=workspace)
    assert result.exit_code != 0


def test_sandbox_read_aws_credentials(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    aws_dir = Path(os.environ.get("HOME", "/tmp")) / ".aws"
    if not aws_dir.exists():
        aws_dir.mkdir(parents=True, exist_ok=True)

    dummy_creds = aws_dir / "credentials"
    dummy_creds.write_text("secret")

    result = manager.execute(["cat", dummy_creds.as_posix()], workspace_root=workspace)
    assert result.exit_code != 0

    # cleanup
    dummy_creds.unlink()


@pytest.mark.parametrize(
    "cred_file", [".kube/config", ".npmrc", ".docker/config.json", ".gcp/credentials", ".netrc"]
)
def test_sandbox_read_various_credentials(manager, workspace, cred_file):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    home = Path(os.environ.get("HOME", "/tmp"))
    target = home / cred_file

    if not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text("secret")

    try:
        result = manager.execute(["cat", target.as_posix()], workspace_root=workspace)
        assert result.exit_code != 0
    finally:
        target.unlink()


def test_sandbox_read_git_dir(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    git_file = workspace / ".git" / "config"
    git_file.parent.mkdir(parents=True, exist_ok=True)
    git_file.write_text("dummy")

    result = manager.execute(["cat", git_file.as_posix()], workspace_root=workspace)
    assert result.exit_code != 0


def test_sandbox_read_config_dir(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    config_dir = Path(os.environ.get("HOME", "/tmp")) / ".config"
    config_dir.mkdir(parents=True, exist_ok=True)

    dummy_file = config_dir / "dummy_config.txt"
    dummy_file.write_text("secret")

    try:
        result = manager.execute(["cat", dummy_file.as_posix()], workspace_root=workspace)
        assert result.exit_code != 0
    finally:
        dummy_file.unlink()


def test_sandbox_symlink_escape(manager, workspace, tmp_path):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    outside_file = tmp_path / "outside_secret.txt"
    outside_file.write_text("secret")

    symlink_file = workspace / "escape_link"
    os.symlink(str(outside_file), str(symlink_file))

    try:
        result = manager.execute(["cat", symlink_file.as_posix()], workspace_root=workspace)
        assert result.exit_code != 0
    finally:
        symlink_file.unlink()
        outside_file.unlink()


def test_sandbox_command_timeout(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    # Use timeout=1 to trigger timeout quickly
    result = manager.execute(["sleep", "2"], workspace_root=workspace, timeout=1)
    assert result.exit_code == -1
    assert "timed out" in result.stderr.lower()


def test_sandbox_network_denial_localhost(manager, workspace):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    # Try to ping localhost (should be blocked by network sandbox)
    result = manager.execute(
        ["ping", "-c", "1", "-t", "1", "127.0.0.1"], workspace_root=workspace, timeout=3
    )
    assert result.exit_code != 0


def test_sandbox_read_outside_workspace(manager, workspace, tmp_path):
    if platform.system() != "Darwin":
        pytest.skip("Sandbox only supported on macOS")

    outside = tmp_path / "outside_read.txt"
    outside.write_text("secret")
    result = manager.execute(["cat", outside.as_posix()], workspace_root=workspace)

    assert result.exit_code != 0
    assert "secret" not in result.stdout
