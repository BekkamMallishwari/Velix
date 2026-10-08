import pytest

from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.secrets import SecretStore


def test_secret_store_register_and_create_env():
    store = SecretStore()
    store.register("TEST_KEY", "super_secret_value")

    # allowlisted injection
    env = store.create_environment(["TEST_KEY"])
    assert "TEST_KEY" in env
    assert env["TEST_KEY"] == "super_secret_value"

    # unapproved secret not injected
    store.register("UNAPPROVED_KEY", "another_secret")
    env = store.create_environment(["TEST_KEY"])
    assert "UNAPPROVED_KEY" not in env


def test_stdout_redaction():
    store = SecretStore()
    store.register("API_KEY", "secret_12345")

    # stdout redaction
    text = "Connecting with secret_12345 and ab!"
    redacted = store.redact(text)
    assert "secret_12345" not in redacted
    assert "***REDACTED***" in redacted


def test_short_secrets_rejected():
    store = SecretStore()
    with pytest.raises(ValueError, match="too short"):
        store.register("SHORT", "ab")


def test_missing_invalid_secret_names():
    store = SecretStore()
    store.register("KEY", "val")
    env = store.create_environment(["KEY", "MISSING_KEY"])
    assert "KEY" in env
    assert "MISSING_KEY" not in env


def test_empty_secrets():
    store = SecretStore()
    with pytest.raises(ValueError, match="must not be empty"):
        store.register("EMPTY", "")
    with pytest.raises(ValueError, match="must not be empty"):
        store.register("", "val")


def test_regex_special_characters():
    store = SecretStore()
    store.register("REGEX_KEY", "secret.*+$value")
    text = "The secret is secret.*+$value here"
    redacted = store.redact(text)
    assert "secret.*+$value" not in redacted
    assert "***REDACTED***" in redacted


def test_cleanup():
    store = SecretStore()
    store.register("KEY", "val123")
    store.cleanup()
    env = store.create_environment(["KEY"])
    assert "KEY" not in env
    assert store.redact("val123") == "val123"


def test_no_secret_in_sandbox_result(tmp_path):
    manager = SandboxManager(_force_none=True)
    from velix_agent.sandbox.backends.base import SandboxBackend
    from velix_agent.sandbox.result import SandboxResult

    class MockBackend(SandboxBackend):
        @classmethod
        def get_capabilities(cls):
            from velix_agent.sandbox.policy import SandboxCapabilities

            return SandboxCapabilities(
                filesystem_isolation="SUPPORTED",
                network_isolation="SUPPORTED",
                cpu_limit="SUPPORTED",
                memory_limit="SUPPORTED",
                process_limit="SUPPORTED",
                timeout="SUPPORTED",
                output_limit="SUPPORTED",
                secret_filtering="SUPPORTED",
                disk_limit="SUPPORTED",
                runtime_isolation="SUPPORTED",
                observability="SUPPORTED",
                security_hardening="SUPPORTED",
            )

        def execute(self, command, policy, timeout=30):
            # simulate output containing the secret
            return SandboxResult(
                stdout="Output has secret_abcd_1234",
                stderr="Error has secret_abcd_1234",
                exit_code=0,
                command=["echo", "secret_abcd_1234"],
            )

    manager.backend = MockBackend()

    res = manager.execute(
        command=["echo", "secret_abcd_1234"],
        workspace_root=tmp_path,
        secrets={"MOCK_KEY": "secret_abcd_1234"},
    )

    assert "secret_abcd_1234" not in res.stdout
    assert "secret_abcd_1234" not in res.stderr
    assert "secret_abcd_1234" not in res.command[1]
    assert "***REDACTED***" in res.stdout
    assert "***REDACTED***" in res.stderr
    assert "***REDACTED***" in res.command[1]
