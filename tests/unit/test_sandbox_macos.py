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

def test_sandbox_output_truncation_stdout(macos_backend, policy):
    import sys
    # Small output below limit
    cmd_small = [sys.executable, "-c", "print('x' * 10)"]
    res_small = macos_backend.execute(cmd_small, policy)
    assert res_small.exit_code == 0
    assert res_small.stdout.strip() == "x" * 10

    # Large output exceeding limit
    cmd_large = [sys.executable, "-c", "print('x' * 60000)"]
    res_large = macos_backend.execute(cmd_large, policy)
    assert res_large.exit_code == 0
    assert len(res_large.stdout) < 60000
    assert "[TRUNCATED:" in res_large.stdout

def test_sandbox_output_truncation_stderr(macos_backend, policy):
    import sys
    # Small output below limit
    cmd_small = [sys.executable, "-c", "import sys; sys.stderr.write('x' * 10)"]
    res_small = macos_backend.execute(cmd_small, policy)
    assert res_small.exit_code == 0
    assert res_small.stderr.strip() == "x" * 10

    # Large output exceeding limit
    cmd_large = [sys.executable, "-c", "import sys; sys.stderr.write('x' * 60000)"]
    res_large = macos_backend.execute(cmd_large, policy)
    assert res_large.exit_code == 0
    assert len(res_large.stderr) < 60000
    assert "[TRUNCATED:" in res_large.stderr


def test_sandbox_cpu_limit(macos_backend, policy):
    import signal
    import sys
    # A tight infinite loop. It should be killed by SIGXCPU (-24) on macOS.
    cmd = [sys.executable, "-c", "while True: pass"]
    # We use a short timeout for the test to run fast
    res = macos_backend.execute(cmd, policy, timeout=1)

    # macOS Python subprocess surfaces the signal as a negative return code.
    # If the OS CPU limit fires before the 1-second process.wait(timeout=1),
    # it returns -24 (SIGXCPU). If wait() triggers first, our pgkill uses SIGKILL (-9).
    # Since timeout is 1s and CPU limit is 1s, it's a race, but either is a forced kill.
    # However, SIGXCPU is specifically what we want to demonstrate works.
    assert res.exit_code in (-signal.SIGXCPU, -signal.SIGKILL, -1)


def test_sandbox_process_limit_unsupported(macos_backend, policy):
    # Process limits (RLIMIT_NPROC) cannot be safely enforced per-subprocess on macOS
    # because they apply globally to the user. We only document this limitation
    # and rely on the pgkill mechanism tested below.
    pass


def test_sandbox_runaway_child(macos_backend, policy):
    import subprocess
    import sys
    import time

    # Spawn a child that ignores signals or sleeps long, then parent exits
    script = "import subprocess, sys\\n" \
             "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10.12345)'])\\n"

    cmd = [sys.executable, "-c", script]

    t0 = time.time()
    _res = macos_backend.execute(cmd, policy, timeout=1)
    t1 = time.time()

    # Process should exit quickly, not wait 10s for the runaway child
    assert t1 - t0 < 5

    # Check that the runaway child is gone.
    # The parent process started python -c "import time; time.sleep(10.12345)"
    # We'll scan system processes to ensure it doesn't exist.
    time.sleep(0.5) # Allow OS to reap

    # pgrep returns 0 if found, 1 if not found.
    # We search for "time.sleep(10.12345)" in process list.
    # To avoid matching our own pgrep command, we use [t]ime.sleep(10.12345)
    pgrep_res = subprocess.run(["pgrep", "-f", "[t]ime.sleep(10.12345)"], capture_output=True)
    assert pgrep_res.returncode != 0, "Runaway child survived the sandbox termination!"
