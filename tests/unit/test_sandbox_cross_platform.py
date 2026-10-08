import platform
import sys
from pathlib import Path

import pytest

from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.result import SandboxError


def test_sandbox_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force platform.system() to return something unsupported
    monkeypatch.setattr(platform, "system", lambda: "UnknownOS")

    manager = SandboxManager()
    assert manager.backend is None

    with pytest.raises(SandboxError, match="Sandbox backend unavailable"):
        manager.execute(["echo", "hello"], "/tmp")


def test_sandbox_capabilities() -> None:
    manager = SandboxManager()
    caps = manager.get_capabilities()
    assert caps is not None
    # We just ensure it returns a valid capability object without crashing
    assert hasattr(caps, "filesystem_isolation")


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_cross_platform_basic_execution(tmp_path: Path) -> None:
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"
    result = manager.execute(["echo", "hello sandbox"], tmp_path, allow_network=allow_net)

    assert result.exit_code == 0
    assert "hello sandbox" in result.stdout


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_cross_platform_timeout(tmp_path: Path) -> None:
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"

    # Use sys.executable to sleep
    result = manager.execute(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        tmp_path,
        timeout=1,
        allow_network=allow_net,
    )

    assert result.exit_code == -1
    assert "timed out" in result.stderr


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_cross_platform_workspace_restriction(tmp_path: Path) -> None:
    # Basic check that the process starts in the workspace
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"

    code = "import os\nprint(os.getcwd())\n"
    result = manager.execute([sys.executable, "-c", code], tmp_path, allow_network=allow_net)

    assert result.exit_code == 0
    # On macOS, tmp_path might be resolved to /private/var/..., check if samefile
    out_path = Path(result.stdout.strip())
    assert out_path.resolve() == tmp_path.resolve()


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_network_isolation_enforcement(tmp_path: Path) -> None:
    manager = SandboxManager()
    caps = manager.get_capabilities()

    if caps.network_isolation == "UNSUPPORTED":
        # Must fail if we demand network isolation (allow_network=False)
        with pytest.raises(
            SandboxError, match="Network isolation is unsupported by the active backend"
        ):
            manager.execute(["echo", "hello"], tmp_path, allow_network=False)

        # Must succeed if we accept the risk (allow_network=True)
        result = manager.execute(["echo", "hello"], tmp_path, allow_network=True)
        assert result.exit_code == 0
    else:
        # Must succeed with strict isolation (allow_network=False)
        result = manager.execute(["echo", "hello"], tmp_path, allow_network=False)
        assert result.exit_code == 0


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_disk_limit_unsupported() -> None:
    manager = SandboxManager()
    caps = manager.get_capabilities()

    # We explicitly verify that NO backend falsely claims disk_limit support
    # since we don't have a true quota enforcement mechanism implemented.
    assert caps.disk_limit == "UNSUPPORTED"
