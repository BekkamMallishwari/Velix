import os
import platform
from pathlib import Path

import pytest

from velix_agent.sandbox.backends.macos import MacOSSandboxBackend
from velix_agent.sandbox.policy import SandboxPolicy


@pytest.fixture
def macos_backend():
    if platform.system() != "Darwin":
        pytest.skip("macOS specific test")
    return MacOSSandboxBackend()

@pytest.fixture
def workspace_root(tmp_path):
    # We want to test with the actual project root for some tests to use .venv
    # but for isolation, a tmp path is generally better.
    # The requirement specifically asks to test ".venv" execution,
    # so we use the actual project root.
    return Path(__file__).parent.parent.parent.resolve()

@pytest.fixture
def policy(workspace_root):
    return SandboxPolicy(workspace_root=workspace_root, allow_network=False)

def test_sandbox_normal_python(macos_backend, policy):
    result = macos_backend.execute([".venv/bin/python", "-c", "print('hello')"], policy)
    assert result.exit_code == 0
    assert "hello" in result.stdout

def test_sandbox_pytest_venv(macos_backend, policy):
    # Run a very simple, fast test so it doesn't take forever
    result = macos_backend.execute([".venv/bin/pytest", "tests/unit/test_config.py", "-v"], policy)
    assert result.exit_code == 0

def test_sandbox_workspace_read_write(macos_backend, policy):
    test_file = policy.workspace_root / "test_sandbox_rw.txt"
    try:
        write_res = macos_backend.execute(["sh", "-c", f"echo 'test' > {test_file.name}"], policy)
        assert write_res.exit_code == 0

        read_res = macos_backend.execute(["cat", test_file.name], policy)
        assert read_res.exit_code == 0
        assert "test" in read_res.stdout
    finally:
        if test_file.exists():
            test_file.unlink()

def test_sandbox_outside_workspace_blocked(macos_backend, policy):
    read_res = macos_backend.execute(["cat", "/etc/hosts"], policy)
    assert read_res.exit_code != 0

    # Wait, /tmp is now explicitly allowed!
    # Let's test a directory that is NOT allowed like /Users or /etc
    write_res2 = macos_backend.execute(["touch", "/etc/sandbox_outside_test.txt"], policy)
    assert write_res2.exit_code != 0

def test_sandbox_ssh_aws_blocked(macos_backend, policy):
    home = os.environ.get("HOME", "/tmp")

    ssh_res = macos_backend.execute(["ls", f"{home}/.ssh"], policy)
    assert ssh_res.exit_code != 0

    aws_res = macos_backend.execute(["ls", f"{home}/.aws"], policy)
    assert aws_res.exit_code != 0

def test_sandbox_git_blocked(macos_backend, policy):
    git_res = macos_backend.execute(["ls", ".git"], policy)
    assert git_res.exit_code != 0

    git_write_res = macos_backend.execute(["touch", ".git/test_file"], policy)
    assert git_write_res.exit_code != 0

def test_sandbox_network_blocked(macos_backend, policy):
    # Test network blocked. Since we allowed /private/etc/ssl,
    # curl should now fail with a network error, or at least not fail
    # due to openssl.cnf, but it should still fail because network is blocked.
    cmd = ["curl", "-I", "--connect-timeout", "2", "https://1.1.1.1"]
    net_res = macos_backend.execute(cmd, policy)
    assert net_res.exit_code != 0
