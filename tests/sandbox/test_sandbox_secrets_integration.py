import os
from pathlib import Path

import pytest

from velix_agent.sandbox.manager import SandboxManager


@pytest.fixture
def sandbox_manager() -> SandboxManager:
    return SandboxManager()


def test_host_environment_not_inherited(sandbox_manager: SandboxManager, tmp_path: Path) -> None:
    os.environ["SUPER_SECRET_HOST_KEY"] = "host_secret_value"
    try:
        # Check if environment is printed
        # Depending on OS, 'env' or 'set' prints the environment
        import platform

        cmd = ["set"] if platform.system() == "Windows" else ["env"]

        res = sandbox_manager.execute(
            command=cmd, workspace_root=tmp_path, mode="BALANCED", allow_network=True
        )

        assert "SUPER_SECRET_HOST_KEY" not in res.stdout
        assert "host_secret_value" not in res.stdout
    finally:
        del os.environ["SUPER_SECRET_HOST_KEY"]


def test_secret_injection_and_redaction(sandbox_manager: SandboxManager, tmp_path: Path) -> None:
    # Register a secret
    secret_value = "my_custom_injected_secret_123"

    import platform

    if platform.system() == "Windows":
        cmd = ["cmd.exe", "/c", "echo", "%INJECTED_SECRET%"]
    else:
        cmd = ["sh", "-c", "echo $INJECTED_SECRET"]

    res = sandbox_manager.execute(
        command=cmd,
        workspace_root=tmp_path,
        secrets={"INJECTED_SECRET": secret_value},
        mode="BALANCED",
        allow_network=True,
    )

    # The output should NOT contain the secret value directly
    assert secret_value not in res.stdout
    assert secret_value not in res.stderr

    # It SHOULD contain the REDACTED string if the secret was printed
    # (Since it printed the variable, it should be redacted)
    assert "***REDACTED***" in res.stdout
