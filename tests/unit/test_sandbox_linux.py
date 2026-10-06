import platform
from pathlib import Path

import pytest

from velix_agent.sandbox.backends.linux import LinuxSandboxBackend
from velix_agent.sandbox.policy import SandboxPolicy


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific sandbox tests")
def test_linux_backend_capabilities() -> None:
    caps = LinuxSandboxBackend.get_capabilities()
    assert caps.filesystem_isolation == "SUPPORTED"
    assert caps.network_isolation == "SUPPORTED"


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific sandbox tests")
def test_linux_backend_execution(tmp_path: Path) -> None:
    backend = LinuxSandboxBackend()
    policy = SandboxPolicy(workspace_root=tmp_path, allow_network=False)

    # Simple execution test, relies on bwrap being installed
    try:
        result = backend.execute(["echo", "linux"], policy)
        assert result.exit_code == 0
        assert "linux" in result.stdout
    except Exception as e:
        if "Bubblewrap (bwrap) is required" in str(e):
            pytest.skip("bwrap not installed on this Linux host")
        raise
