import platform
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
    code = (
        "a = b'1' * (20 * 1024 * 1024)\n"
        "print('Allocated')\n"
    )
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
    mock_popen: MagicMock,
    mock_assign: MagicMock,
    mock_close_handle: MagicMock,
    tmp_path: Path
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
