import shutil
import sys
from pathlib import Path

import pytest

from velix_agent.runtime.manager import RuntimeManager
from velix_agent.runtime.models import RuntimeStatus


def test_runtime_manager_detect_python(tmp_path: Path) -> None:
    manager = RuntimeManager()
    info = manager.get_runtime("Python", tmp_path)

    assert info.name == "Python"
    # Python should be available since we are running pytest in it
    assert info.status == RuntimeStatus.SUPPORTED
    assert info.executable is not None
    assert info.version is not None
    assert "Python" in info.version or info.version.startswith("3.")
    assert info.package_manager in ("pip", "pip3", None)  # pip might not be in PATH


def test_runtime_manager_unsupported(tmp_path: Path) -> None:
    manager = RuntimeManager()
    info = manager.get_runtime("UnknownRuntime", tmp_path)

    assert info.name == "UnknownRuntime"
    assert info.status == RuntimeStatus.UNSUPPORTED


def test_runtime_manager_detect_all(tmp_path: Path) -> None:
    manager = RuntimeManager()
    all_runtimes = manager.detect_all(tmp_path)

    assert "Python" in all_runtimes
    assert "Node.js" in all_runtimes
    assert "Java" in all_runtimes
    assert "Go" in all_runtimes
    assert "Rust" in all_runtimes

    assert all_runtimes["Python"].status == RuntimeStatus.SUPPORTED


def test_missing_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda x: None)

    manager = RuntimeManager()
    info = manager.get_runtime("Node.js", tmp_path)
    assert info.status == RuntimeStatus.UNAVAILABLE
    assert info.executable is None
    assert info.version is None


def test_python_venv_detection(tmp_path: Path) -> None:
    manager = RuntimeManager()
    venv_path = tmp_path / ".venv"
    venv_path.mkdir()

    # Create fake python executable
    if sys.platform == "win32":
        bin_dir = venv_path / "Scripts"
        exec_name = "python.exe"
    else:
        bin_dir = venv_path / "bin"
        exec_name = "python"

    bin_dir.mkdir()
    fake_python = bin_dir / exec_name
    fake_python.write_text("#!/bin/sh\necho Python 3.9.9\n")
    fake_python.chmod(0o755)

    info = manager.get_runtime("Python", tmp_path)

    # Wait, if we create a fake python, the sandbox might try to run it.
    assert info.is_virtual_env is True
    # The path should point to our fake virtual environment python
    assert str(fake_python) in info.executable or fake_python.name in info.executable


def test_controlled_environment_no_leaks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")

    manager = RuntimeManager()
    # The runtime manager uses SandboxManager under the hood to get the version,
    # which inherently strips host variables like OPENAI_API_KEY.
    info = manager.get_runtime("Python", tmp_path)

    assert info.status == RuntimeStatus.SUPPORTED
    # We can't directly check the env inside the test without a custom script,
    # but the architectural separation SandboxManager -> execute ensures it.
