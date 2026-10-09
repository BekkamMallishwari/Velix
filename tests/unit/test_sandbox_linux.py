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
