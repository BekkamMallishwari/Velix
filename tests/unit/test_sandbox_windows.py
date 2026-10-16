import io
import platform
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from velix_agent.sandbox.backends.windows import WindowsSandboxBackend
from velix_agent.sandbox.policy import SandboxPolicy
from velix_agent.sandbox.result import SandboxError


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific tests")
def test_windows_backend_capabilities() -> None:
    caps = WindowsSandboxBackend.get_capabilities()
    assert caps.filesystem_isolation == "UNSUPPORTED"
    assert caps.network_isolation == "UNSUPPORTED"
    assert caps.cpu_limit == "UNSUPPORTED"
    assert caps.memory_limit == "SUPPORTED"
    assert caps.process_limit == "SUPPORTED"
    assert caps.timeout == "SUPPORTED"
    assert caps.output_limit == "SUPPORTED"
    assert caps.secret_filtering == "SUPPORTED"


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific tests")
def test_windows_backend_execution(tmp_path: Path) -> None:
    backend = WindowsSandboxBackend()
    # We must allow network because default deny is not supported on Windows Tier 1
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    result = backend.execute(["cmd.exe", "/c", "echo windows"], policy)

    assert result.exit_code == 0
    assert "windows" in result.stdout.lower()


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific tests")
def test_windows_backend_unsupported_network_isolation(tmp_path: Path) -> None:
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=False)

    with pytest.raises(SandboxError, match="Network isolation is unavailable"):
        backend.execute(["cmd.exe", "/c", "echo windows"], policy)


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific tests")
def test_windows_backend_timeout_and_job_cleanup(tmp_path: Path) -> None:
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    # Run a script that sleeps and spawns a child that sleeps
    code = (
        "import subprocess, time, sys\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])\n"
        "time.sleep(10)\n"
    )
    result = backend.execute([sys.executable, "-c", code], policy, timeout=1)

    assert result.exit_code == -1
    assert "timed out" in result.stderr
    # We assume job termination kills the child process cleanly


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific tests")
def test_windows_backend_memory_limit(tmp_path: Path) -> None:
    backend = WindowsSandboxBackend()
    # 5MB limit
    policy = SandboxPolicy(
        workspace_root=tmp_path, allow_network=True, memory_limit=5 * 1024 * 1024
    )

    # Try to allocate 20MB
    code = "a = b'1' * (20 * 1024 * 1024)\nprint('Allocated')\n"
    # The process should crash/exit before printing 'Allocated'
    result = backend.execute([sys.executable, "-c", code], policy)

    assert "Allocated" not in result.stdout
    assert result.exit_code != 0


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific tests")
def test_windows_backend_process_limit(tmp_path: Path) -> None:
    backend = WindowsSandboxBackend()
    # Limit to 2 processes (1 for Python, 1 for child)
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True, process_limit=2)

    # Try to spawn 3 children
    code = (
        "import subprocess, sys, time\n"
        "procs = []\n"
        "try:\n"
        "    for _ in range(3):\n"
        "        p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2)'])\n"
        "        procs.append(p)\n"
        "    print('Spawned all')\n"
        "except Exception as e:\n"
        "    print('Failed to spawn:', e)\n"
    )
    result = backend.execute([sys.executable, "-c", code], policy)

    # Since process limit is 2 (the main python script is 1, so only 1 child is allowed),
    # it should fail to spawn all 3
    assert "Spawned all" not in result.stdout


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific tests")
def test_windows_secret_filtering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    # Insert dummy secrets into host environment
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "DUMMY_AWS_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "DUMMY_OPENAI_KEY")
    monkeypatch.setenv("GITHUB_TOKEN", "DUMMY_GH_TOKEN")

    code = (
        "import os\n"
        "print('AWS:', os.environ.get('AWS_ACCESS_KEY_ID'))\n"
        "print('OPENAI:', os.environ.get('OPENAI_API_KEY'))\n"
        "print('GITHUB:', os.environ.get('GITHUB_TOKEN'))\n"
    )

    result = backend.execute([sys.executable, "-c", code], policy)

    assert "AWS: None" in result.stdout
    assert "OPENAI: None" in result.stdout
    assert "GITHUB: None" in result.stdout
    assert "DUMMY_AWS_KEY" not in result.stdout


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific tests")
@patch("velix_agent.sandbox.backends.windows.CloseHandle")
@patch("subprocess.Popen")
def test_windows_close_handle_on_popen_failure(
    mock_popen: MagicMock, mock_close_handle: MagicMock, tmp_path: Path
) -> None:
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    mock_popen.side_effect = FileNotFoundError("Executable not found")

    with pytest.raises(
        SandboxError, match="Failed to execute sandboxed command: Executable not found"
    ):
        backend.execute(["invalid_command.exe"], policy)

    assert mock_close_handle.called
    assert mock_close_handle.call_count == 1


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific tests")
@patch("velix_agent.sandbox.backends.windows.CloseHandle")
@patch("velix_agent.sandbox.backends.windows.AssignProcessToJobObject")
@patch("subprocess.Popen")
def test_windows_failed_job_assignment_cleanup(
    mock_popen: MagicMock, mock_assign: MagicMock, mock_close_handle: MagicMock, tmp_path: Path
) -> None:
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    # Mock subprocess.Popen to return a mock process
    mock_process = MagicMock()
    mock_process._handle = 1234
    mock_popen.return_value = mock_process

    # Force assignment to fail
    mock_assign.return_value = False

    # Also mock NtResumeProcess to ensure it's NEVER called
    with patch("velix_agent.sandbox.backends.windows.NtResumeProcess") as mock_resume:
        with pytest.raises(SandboxError, match="Failed to assign process to Job Object"):
            backend.execute(["cmd.exe", "/c", "echo hello"], policy)

        # Process must be killed
        assert mock_process.kill.called
        assert mock_process.wait.called

        # Resume thread MUST NOT be called
        assert not mock_resume.called

    # Handle must be closed
    assert mock_close_handle.called
    assert mock_close_handle.call_count == 1


def test_cross_platform_import() -> None:
    # Importing windows.py should not crash on macOS/Linux
    try:
        from velix_agent.sandbox.backends.windows import WindowsSandboxBackend

        WindowsSandboxBackend()
        # This is enough to verify it doesn't crash on import/instantiation
    except Exception as e:
        pytest.fail(f"Importing Windows backend failed: {e}")


# ===========================================================================
# Focused Mocked Tests for Win32 Cleanup Calls
# Note: Mocked tests do not replace native Windows CI.
# ===========================================================================


def _mock_win_process(
    stdout_data: bytes = b"output\n",
    stderr_data: bytes = b"",
    returncode: int = 0,
) -> MagicMock:
    proc = MagicMock()
    proc._handle = 1234
    proc.stdout = io.BytesIO(stdout_data)
    proc.stderr = io.BytesIO(stderr_data)
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.wait.return_value = returncode
    return proc


def test_windows_cleanup_successful_calls(tmp_path: Path) -> None:
    """Verify successful Win32 cleanup calls and exit code preservation."""
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)
    mock_proc = _mock_win_process(stdout_data=b"hello windows\n", returncode=0)

    with (
        patch("platform.system", return_value="Windows"),
        patch("velix_agent.sandbox.backends.windows.CreateJobObjectW", return_value=1000),
        patch("velix_agent.sandbox.backends.windows.SetInformationJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.AssignProcessToJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.NtResumeProcess", return_value=0),
        patch(
            "velix_agent.sandbox.backends.windows.TerminateJobObject", return_value=True
        ) as mock_term,
        patch("velix_agent.sandbox.backends.windows.CloseHandle", return_value=True) as mock_close,
        patch("subprocess.Popen", return_value=mock_proc),
        patch("velix_agent.sandbox.backends.windows.logger.warning") as mock_warn,
    ):
        result = backend.execute(["cmd.exe", "/c", "echo hello"], policy)

    assert result.exit_code == 0
    assert "hello windows" in result.stdout
    assert mock_term.called
    assert mock_close.called
    mock_close.assert_called_with(1000)
    mock_warn.assert_not_called()


def test_windows_cleanup_terminate_failure_in_execution_observable(tmp_path: Path) -> None:
    """Verify failed TerminateJobObject in execution path captures error and raises."""
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)
    mock_proc = _mock_win_process(returncode=0)

    with (
        patch("platform.system", return_value="Windows"),
        patch("velix_agent.sandbox.backends.windows.CreateJobObjectW", return_value=1000),
        patch("velix_agent.sandbox.backends.windows.SetInformationJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.AssignProcessToJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.NtResumeProcess", return_value=0),
        patch(
            "velix_agent.sandbox.backends.windows.TerminateJobObject", return_value=False
        ),
        patch("velix_agent.sandbox.backends.windows.CloseHandle", return_value=True) as mock_close,
        patch(
            "velix_agent.sandbox.backends.windows.ctypes.GetLastError",
            return_value=5,
            create=True,
        ),
        patch("subprocess.Popen", return_value=mock_proc),
        patch("velix_agent.sandbox.backends.windows.logger.warning") as mock_warn,
    ):
        with pytest.raises(SandboxError) as exc_info:
            backend.execute(["cmd.exe", "/c", "echo hello"], policy)

        # Do not silently treat failed termination as successful cleanup
        assert "Failed to terminate Job Object" in str(exc_info.value)
        assert "5" in str(exc_info.value)

        # Failure is observable via warning log
        assert mock_warn.called
        assert any(
            "TerminateJobObject" in str(call) and "5" in str(call)
            for call in mock_warn.call_args_list
        )

        # CloseHandle is still executed to ensure resources are not leaked
        assert mock_close.called


def test_windows_cleanup_terminate_failure_on_timeout_observable(tmp_path: Path) -> None:
    """Verify failed TerminateJobObject after timeout captures error, emits warning, and raises."""
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)
    mock_proc = _mock_win_process()
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd=["sleep"], timeout=1)

    with (
        patch("platform.system", return_value="Windows"),
        patch("velix_agent.sandbox.backends.windows.CreateJobObjectW", return_value=1000),
        patch("velix_agent.sandbox.backends.windows.SetInformationJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.AssignProcessToJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.NtResumeProcess", return_value=0),
        patch(
            "velix_agent.sandbox.backends.windows.TerminateJobObject", return_value=False
        ),
        patch("velix_agent.sandbox.backends.windows.CloseHandle", return_value=True) as mock_close,
        patch(
            "velix_agent.sandbox.backends.windows.ctypes.GetLastError",
            return_value=5,
            create=True,
        ),
        patch("subprocess.Popen", return_value=mock_proc),
        patch("velix_agent.sandbox.backends.windows.logger.warning") as mock_warn,
    ):
        with pytest.raises(SandboxError) as exc_info:
            backend.execute(["sleep"], policy, timeout=1)

        assert "Failed to terminate Job Object after timeout" in str(exc_info.value)
        assert "5" in str(exc_info.value)
        assert mock_warn.called
        assert mock_close.called


def test_windows_cleanup_terminate_failure_in_cleanup_observable(tmp_path: Path) -> None:
    """Verify failed TerminateJobObject in cleanup block is observable and raises."""
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)
    mock_proc = _mock_win_process(returncode=0)

    # Execution path succeeds (return True), cleanup path fails (return False)
    with (
        patch("platform.system", return_value="Windows"),
        patch("velix_agent.sandbox.backends.windows.CreateJobObjectW", return_value=1000),
        patch("velix_agent.sandbox.backends.windows.SetInformationJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.AssignProcessToJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.NtResumeProcess", return_value=0),
        patch(
            "velix_agent.sandbox.backends.windows.TerminateJobObject", side_effect=[True, False]
        ),
        patch("velix_agent.sandbox.backends.windows.CloseHandle", return_value=True) as mock_close,
        patch(
            "velix_agent.sandbox.backends.windows.ctypes.GetLastError",
            return_value=5,
            create=True,
        ),
        patch("subprocess.Popen", return_value=mock_proc),
        patch("velix_agent.sandbox.backends.windows.logger.warning") as mock_warn,
    ):
        with pytest.raises(SandboxError) as exc_info:
            backend.execute(["cmd.exe", "/c", "echo hello"], policy)

        assert "Failed to terminate Job Object during cleanup" in str(exc_info.value)
        assert "5" in str(exc_info.value)
        assert mock_warn.called
        assert mock_close.called


def test_windows_cleanup_close_handle_failure_observable(tmp_path: Path) -> None:
    """Verify failed CloseHandle captures error, emits warning, and raises SandboxError."""
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)
    mock_proc = _mock_win_process(returncode=0)

    with (
        patch("platform.system", return_value="Windows"),
        patch("velix_agent.sandbox.backends.windows.CreateJobObjectW", return_value=1000),
        patch("velix_agent.sandbox.backends.windows.SetInformationJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.AssignProcessToJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.NtResumeProcess", return_value=0),
        patch("velix_agent.sandbox.backends.windows.TerminateJobObject", return_value=True),
        patch(
            "velix_agent.sandbox.backends.windows.CloseHandle", return_value=False
        ) as mock_close,
        patch(
            "velix_agent.sandbox.backends.windows.ctypes.GetLastError",
            return_value=6,
            create=True,
        ),
        patch("subprocess.Popen", return_value=mock_proc),
        patch("velix_agent.sandbox.backends.windows.logger.warning") as mock_warn,
    ):
        with pytest.raises(SandboxError) as exc_info:
            backend.execute(["cmd.exe", "/c", "echo hello"], policy)

        assert "Failed to close Job Object handle" in str(exc_info.value)
        assert "6" in str(exc_info.value)
        assert mock_close.called
        assert mock_warn.called
        assert any(
            "CloseHandle" in str(call) and "6" in str(call)
            for call in mock_warn.call_args_list
        )


def test_windows_cleanup_failure_does_not_mask_execution_exception(tmp_path: Path) -> None:
    """Verify cleanup failures do not mask original execution exceptions."""
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)

    with (
        patch("platform.system", return_value="Windows"),
        patch("velix_agent.sandbox.backends.windows.CreateJobObjectW", return_value=1000),
        patch("velix_agent.sandbox.backends.windows.SetInformationJobObject", return_value=True),
        patch("subprocess.Popen", side_effect=RuntimeError("Subprocess launch crashed")),
        patch("velix_agent.sandbox.backends.windows.TerminateJobObject", return_value=False),
        patch("velix_agent.sandbox.backends.windows.CloseHandle", return_value=False),
        patch(
            "velix_agent.sandbox.backends.windows.ctypes.GetLastError",
            return_value=6,
            create=True,
        ),
        patch("velix_agent.sandbox.backends.windows.logger.warning") as mock_warn,
    ):
        with pytest.raises(SandboxError) as exc_info:
            backend.execute(["invalid_command.exe"], policy)

        # Original execution error must NOT be masked
        assert "Subprocess launch crashed" in str(exc_info.value)
        assert exc_info.value.__cause__ is not None
        assert "Subprocess launch crashed" in str(exc_info.value.__cause__)

        # Warnings for cleanup failures must still be emitted
        assert mock_warn.called


def test_windows_timeout_preserves_exit_code_and_behavior(tmp_path: Path) -> None:
    """Verify timeout behavior is preserved with exit code -1 and Command timed out stderr."""
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)
    mock_proc = _mock_win_process()
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd=["sleep"], timeout=1)

    with (
        patch("platform.system", return_value="Windows"),
        patch("velix_agent.sandbox.backends.windows.CreateJobObjectW", return_value=1000),
        patch("velix_agent.sandbox.backends.windows.SetInformationJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.AssignProcessToJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.NtResumeProcess", return_value=0),
        patch(
            "velix_agent.sandbox.backends.windows.TerminateJobObject", return_value=True
        ) as mock_term,
        patch("velix_agent.sandbox.backends.windows.CloseHandle", return_value=True),
        patch("subprocess.Popen", return_value=mock_proc),
    ):
        result = backend.execute(["sleep"], policy, timeout=1)

    assert result.exit_code == -1
    assert "Command timed out" in result.stderr
    mock_term.assert_any_call(1000, 1)


def test_windows_non_zero_exit_code_preserved(tmp_path: Path) -> None:
    """Verify existing exit-code behavior is preserved for non-zero process exits."""
    backend = WindowsSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=True)
    mock_proc = _mock_win_process(stdout_data=b"failed\n", returncode=42)

    with (
        patch("platform.system", return_value="Windows"),
        patch("velix_agent.sandbox.backends.windows.CreateJobObjectW", return_value=1000),
        patch("velix_agent.sandbox.backends.windows.SetInformationJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.AssignProcessToJobObject", return_value=True),
        patch("velix_agent.sandbox.backends.windows.NtResumeProcess", return_value=0),
        patch(
            "velix_agent.sandbox.backends.windows.TerminateJobObject", return_value=True
        ) as mock_term,
        patch("velix_agent.sandbox.backends.windows.CloseHandle", return_value=True),
        patch("subprocess.Popen", return_value=mock_proc),
    ):
        result = backend.execute(["exit42.exe"], policy)

    assert result.exit_code == 42
    assert "failed" in result.stdout
    mock_term.assert_any_call(1000, 0)
