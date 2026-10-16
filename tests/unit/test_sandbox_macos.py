import os
import platform
import shutil
import sys
import typing
from pathlib import Path

import pytest

from velix_agent.sandbox.backends.macos import MacOSSandboxBackend
from velix_agent.sandbox.policy import SandboxPolicy


@pytest.fixture
def macos_backend() -> MacOSSandboxBackend:
    if platform.system() != "Darwin" or not shutil.which("sandbox-exec"):
        pytest.skip("macOS sandbox-exec not available")
    return MacOSSandboxBackend()


@pytest.fixture
def workspace_root(tmp_path: typing.Any) -> Path:
    # We want to test with the actual project root for some tests to use .venv
    # but for isolation, a tmp path is generally better.
    # The requirement specifically asks to test ".venv" execution,
    # so we use the actual project root.
    return Path(__file__).parent.parent.parent.resolve()


@pytest.fixture
def policy(workspace_root: Path) -> SandboxPolicy:
    return SandboxPolicy(workspace_root=workspace_root, allow_network=False)


def test_sandbox_normal_python(macos_backend: MacOSSandboxBackend, policy: SandboxPolicy) -> None:
    result = macos_backend.execute([sys.executable, "-c", "print('hello')"], policy)
    assert result.exit_code == 0
    assert "hello" in result.stdout


def test_sandbox_pytest_venv(macos_backend: MacOSSandboxBackend, policy: SandboxPolicy) -> None:
    # Run a very simple, fast test so it doesn't take forever
    result = macos_backend.execute(
        [sys.executable, "-m", "pytest", "tests/unit/test_config.py", "-v"], policy
    )
    assert result.exit_code == 0


def test_sandbox_workspace_read_write(
    macos_backend: MacOSSandboxBackend, policy: SandboxPolicy
) -> None:
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


def test_sandbox_outside_workspace_blocked(
    macos_backend: MacOSSandboxBackend, policy: SandboxPolicy
) -> None:
    read_res = macos_backend.execute(["cat", "/etc/hosts"], policy)
    assert read_res.exit_code != 0

    write_res = macos_backend.execute(["touch", "/etc/sandbox_outside_test.txt"], policy)
    assert write_res.exit_code != 0


def test_sandbox_tmp_outside_workspace_blocked(
    macos_backend: MacOSSandboxBackend, policy: SandboxPolicy
) -> None:
    # Regression test for /tmp isolation: verify that files in /tmp outside
    # the workspace cannot be read or written to from the sandbox.
    outside_tmp = Path("/tmp") / f"velix_test_outside_{os.getpid()}.txt"
    try:
        outside_tmp.write_text("secret_tmp_content")
        read_res = macos_backend.execute(["cat", outside_tmp.as_posix()], policy)
        assert read_res.exit_code != 0
        assert "secret_tmp_content" not in read_res.stdout

        write_res = macos_backend.execute(
            ["touch", f"/tmp/velix_test_write_{os.getpid()}.txt"], policy
        )
        assert write_res.exit_code != 0
    finally:
        outside_tmp.unlink(missing_ok=True)


def test_sandbox_symlink_escape_tmp_blocked(
    macos_backend: MacOSSandboxBackend, policy: SandboxPolicy
) -> None:
    # Regression test for symlink escape: a symlink inside the workspace
    # pointing to a file in /tmp outside the workspace must not permit reading.
    outside_tmp = Path("/tmp") / f"velix_test_symlink_outside_{os.getpid()}.txt"
    symlink_in_ws = policy.workspace_root / f"escape_link_{os.getpid()}"
    try:
        outside_tmp.write_text("symlink_secret")
        os.symlink(str(outside_tmp), str(symlink_in_ws))
        res = macos_backend.execute(["cat", symlink_in_ws.name], policy)
        assert res.exit_code != 0
        assert "symlink_secret" not in res.stdout
    finally:
        symlink_in_ws.unlink(missing_ok=True)
        outside_tmp.unlink(missing_ok=True)


def test_sandbox_profile_does_not_contain_blanket_tmp(
    macos_backend: MacOSSandboxBackend, policy: SandboxPolicy
) -> None:
    profile = macos_backend._generate_profile(policy)
    assert '(subpath "/tmp")' not in profile
    assert '(subpath "/private/tmp")' not in profile


def test_sandbox_profile_path_escaping(macos_backend: MacOSSandboxBackend) -> None:
    """Verify that special characters in paths are properly escaped for Seatbelt profiles."""
    raw = '/path/with/"quotes"\\and\nnewlines\r'
    escaped = MacOSSandboxBackend._escape_seatbelt_path(raw)
    assert '"' not in escaped.replace('\\"', "")
    assert "\n" not in escaped
    assert "\r" not in escaped
    assert '\\"' in escaped
    assert "\\\\" in escaped

    # Verify that a policy with unusual workspace characters produces escaped rules
    weird_ws = Path('/tmp/velix "inject" test')
    weird_policy = SandboxPolicy(workspace_root=weird_ws)
    profile = macos_backend._generate_profile(weird_policy)
    assert 'velix \\"inject\\" test' in profile
    assert 'velix "inject" test' not in profile


def test_sandbox_ssh_aws_blocked(macos_backend: MacOSSandboxBackend, policy: SandboxPolicy) -> None:
    home = os.environ.get("HOME", "/tmp")

    ssh_res = macos_backend.execute(["ls", f"{home}/.ssh"], policy)
    assert ssh_res.exit_code != 0

    aws_res = macos_backend.execute(["ls", f"{home}/.aws"], policy)
    assert aws_res.exit_code != 0


def test_sandbox_git_blocked(macos_backend: MacOSSandboxBackend, policy: SandboxPolicy) -> None:
    git_res = macos_backend.execute(["ls", ".git"], policy)
    assert git_res.exit_code != 0

    git_write_res = macos_backend.execute(["touch", ".git/test_file"], policy)
    assert git_write_res.exit_code != 0


def test_sandbox_network_blocked(macos_backend: MacOSSandboxBackend, policy: SandboxPolicy) -> None:
    # Test network blocked. Since we allowed /private/etc/ssl,
    # curl should now fail with a network error, or at least not fail
    # due to openssl.cnf, but it should still fail because network is blocked.
    cmd = ["curl", "-I", "--connect-timeout", "2", "https://1.1.1.1"]
    net_res = macos_backend.execute(cmd, policy)
    assert net_res.exit_code != 0


def test_sandbox_output_truncation_stdout(
    macos_backend: MacOSSandboxBackend, policy: SandboxPolicy
) -> None:
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


def test_sandbox_output_truncation_stderr(
    macos_backend: MacOSSandboxBackend, policy: SandboxPolicy
) -> None:
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


def test_sandbox_cpu_limit(macos_backend: MacOSSandboxBackend, policy: SandboxPolicy) -> None:
    import signal
    import sys

    # Enable CPU limit explicitly on policy
    policy.cpu_limit = True

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


def test_macos_cpu_limit_rlimit_enforcement(
    macos_backend: MacOSSandboxBackend, workspace_root: Path
) -> None:
    """Verify that macOS applies RLIMIT_CPU when policy.cpu_limit=True and not when False."""
    code = "import resource; print(resource.getrlimit(resource.RLIMIT_CPU)[0])"

    # 1. cpu_limit=False (default): RLIMIT_CPU must not be set to timeout
    policy_no_limit = SandboxPolicy(
        workspace_root=workspace_root, cpu_limit=False, allow_network=False
    )
    res_no_limit = macos_backend.execute(
        [sys.executable, "-c", code], policy_no_limit, timeout=10
    )
    assert res_no_limit.exit_code == 0
    cur_limit = int(res_no_limit.stdout.strip())
    # Should be default/unlimited, not the 10-second timeout
    assert cur_limit != 10
    assert cur_limit >= 1000

    # 2. cpu_limit=True: RLIMIT_CPU must be set to timeout
    policy_with_limit = SandboxPolicy(
        workspace_root=workspace_root, cpu_limit=True, allow_network=False
    )
    res_with_limit = macos_backend.execute(
        [sys.executable, "-c", code], policy_with_limit, timeout=10
    )
    assert res_with_limit.exit_code == 0
    assert int(res_with_limit.stdout.strip()) == 10


def test_macos_backend_preexec_rlimit_invocation(workspace_root: Path) -> None:
    """Verify that set_limits calls resource.setrlimit only when policy.cpu_limit is True."""
    backend = MacOSSandboxBackend()
    import resource
    from unittest.mock import MagicMock, patch

    captured_preexec_fns: list[typing.Any] = []

    def mock_popen(*args: typing.Any, **kwargs: typing.Any) -> MagicMock:
        captured_preexec_fns.append(kwargs.get("preexec_fn"))
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.stdout = None
        mock_proc.stderr = None
        mock_proc.wait.return_value = 0
        return mock_proc

    # Case 1: cpu_limit=False (default)
    pol_false = SandboxPolicy(workspace_root=workspace_root, cpu_limit=False)
    with patch("platform.system", return_value="Darwin"), \
         patch("subprocess.Popen", side_effect=mock_popen), \
         patch.object(MacOSSandboxBackend, "_read_stream"):
        backend.execute(["echo", "hi"], pol_false, timeout=10)

    assert len(captured_preexec_fns) == 1
    preexec_false = captured_preexec_fns[0]
    assert preexec_false is not None
    with patch("os.setpgrp"), patch("resource.setrlimit") as mock_setrlimit:
        preexec_false()
        mock_setrlimit.assert_not_called()

    # Case 2: cpu_limit=True
    captured_preexec_fns.clear()
    pol_true = SandboxPolicy(workspace_root=workspace_root, cpu_limit=True)
    with patch("platform.system", return_value="Darwin"), \
         patch("subprocess.Popen", side_effect=mock_popen), \
         patch.object(MacOSSandboxBackend, "_read_stream"):
        backend.execute(["echo", "hi"], pol_true, timeout=10)

    assert len(captured_preexec_fns) == 1
    preexec_true = captured_preexec_fns[0]
    assert preexec_true is not None
    with patch("os.setpgrp"), patch("resource.setrlimit") as mock_setrlimit:
        preexec_true()
        mock_setrlimit.assert_called_once_with(resource.RLIMIT_CPU, (10, 10))



def test_sandbox_process_limit_unsupported(
    macos_backend: MacOSSandboxBackend, policy: SandboxPolicy
) -> None:
    # Process limits (RLIMIT_NPROC) cannot be safely enforced per-subprocess on macOS
    # because they apply globally to the user. We only document this limitation
    # and rely on the pgkill mechanism tested below.
    pass


def test_sandbox_runaway_child(macos_backend: MacOSSandboxBackend, policy: SandboxPolicy) -> None:
    import subprocess
    import sys
    import time

    # Spawn a child that ignores signals or sleeps long, then parent exits
    script = (
        "import subprocess, sys\\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10.12345)'])\\n"
    )

    cmd = [sys.executable, "-c", script]

    t0 = time.time()
    _res = macos_backend.execute(cmd, policy, timeout=1)
    t1 = time.time()

    # Process should exit quickly, not wait 10s for the runaway child
    assert t1 - t0 < 5

    # Check that the runaway child is gone.
    # The parent process started python -c "import time; time.sleep(10.12345)"
    # We'll scan system processes to ensure it doesn't exist.
    time.sleep(0.5)  # Allow OS to reap

    # pgrep returns 0 if found, 1 if not found.
    # We search for "time.sleep(10.12345)" in process list.
    # To avoid matching our own pgrep command, we use [t]ime.sleep(10.12345)
    pgrep_res = subprocess.run(["pgrep", "-f", "[t]ime.sleep(10.12345)"], capture_output=True)
    assert pgrep_res.returncode != 0, "Runaway child survived the sandbox termination!"


def test_macos_detached_child_cleanup_on_timeout(
    macos_backend: MacOSSandboxBackend, policy: SandboxPolicy
) -> None:
    """Verify that a child attempting to detach with setsid() is terminated on timeout."""
    import signal
    import sys
    import time

    pid_file = policy.workspace_root / f"detached_{os.getpid()}.pid"
    script = (
        "import os, time, sys\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    os.setsid()\n"
        f"    with open({str(pid_file)!r}, 'w') as f:\n"
        "        f.write(str(os.getpid()))\n"
        "    time.sleep(20)\n"
        "    sys.exit(0)\n"
        "time.sleep(20)\n"
    )

    t0 = time.time()
    res = macos_backend.execute([sys.executable, "-c", script], policy, timeout=1)
    elapsed = time.time() - t0

    assert res.exit_code == -1
    assert elapsed < 5.0
    assert pid_file.exists()

    child_pid = int(pid_file.read_text().strip())
    pid_file.unlink(missing_ok=True)

    time.sleep(0.5)
    try:
        os.kill(child_pid, 0)
        alive = True
    except OSError:
        alive = False

    if alive:
        os.kill(child_pid, signal.SIGKILL)

    assert not alive, "Detached setsid() child survived timeout termination!"
