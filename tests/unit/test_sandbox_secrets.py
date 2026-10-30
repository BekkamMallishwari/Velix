import pytest

from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.result import OUTPUT_TRUNCATION_MARKER
from velix_agent.sandbox.secrets import REDACTED_PLACEHOLDER, SecretStore

# ---------------------------------------------------------------------------
# Baseline tests (unchanged from original)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Phase 3 regression tests — substring ordering
# ---------------------------------------------------------------------------


def test_redact_longer_secret_before_shorter_substring():
    """Longer secrets must be replaced before shorter substring secrets.

    Before the fix, dict insertion order caused "pass" to be processed before
    "password", turning "password" into "***REDACTED***word".
    """
    store = SecretStore()
    # Register shorter secret first so insertion order would process it first
    # without the length-sort fix.
    store.register("short", "pass")
    store.register("long", "password")

    result = store.redact("my password is pass")

    assert "password" not in result, "full longer secret must be redacted"
    assert f"{REDACTED_PLACEHOLDER}word" not in result, (
        "residue '***REDACTED***word' must not appear"
    )
    assert result == f"my {REDACTED_PLACEHOLDER} is {REDACTED_PLACEHOLDER}"


def test_redact_multiple_overlapping_secrets():
    """Both secrets in an overlapping pair ('abcd'/'cdef') merge into one placeholder."""
    store = SecretStore()
    store.register("a", "abcd")
    store.register("b", "cdef")

    result = store.redact("abcdef")

    assert "abcd" not in result
    assert "cdef" not in result
    assert result == REDACTED_PLACEHOLDER


def test_redact_partially_overlapping_secrets():
    """Secrets that overlap partially ('abcdef' and 'defghi') must be merged cleanly."""
    store = SecretStore()
    store.register("s1", "abcdef")
    store.register("s2", "defghi")

    result = store.redact("header abcdefghi footer")

    assert "abcdef" not in result
    assert "defghi" not in result
    assert result == f"header {REDACTED_PLACEHOLDER} footer"


def test_redact_chain_overlapping_secrets():
    """Three secrets overlapping in a chain ('alpha_tok', 'tok_beta', 'beta_gamma')."""
    store = SecretStore()
    store.register("s1", "alpha_tok")
    store.register("s2", "tok_beta")
    store.register("s3", "beta_gamma")

    result = store.redact("url: alpha_tok_beta_gamma/end")

    assert "alpha_tok" not in result
    assert "tok_beta" not in result
    assert "beta_gamma" not in result
    assert result == f"url: {REDACTED_PLACEHOLDER}/end"


def test_redact_secret_appearing_multiple_times():
    """Every occurrence of a secret value must be redacted."""
    store = SecretStore()
    store.register("tok", "TOKEN_XYZ")

    result = store.redact("first TOKEN_XYZ then TOKEN_XYZ again")

    assert "TOKEN_XYZ" not in result
    assert result.count(REDACTED_PLACEHOLDER) == 2


def test_redact_no_false_positive_on_safe_output():
    """Output with no secret content must pass through unchanged."""
    store = SecretStore()
    store.register("key", "SECRETVALUE")

    safe = "hello world this is safe output"
    assert store.redact(safe) == safe


# ---------------------------------------------------------------------------
# Phase 3 regression tests — truncation-boundary leakage (explicit flag)
# ---------------------------------------------------------------------------


def test_redact_partial_secret_at_boundary_with_flag():
    """A secret prefix at the truncation boundary is stripped when truncated=True.

    The body ends with "SEC", the first 3 chars of "SECRETVALUE".  With
    truncated=True, redact() must remove that prefix and preserve the marker.
    """
    store = SecretStore()
    store.register("key", "SECRETVALUE")

    body = "normal output SEC"
    text = body + OUTPUT_TRUNCATION_MARKER

    result = store.redact(text, truncated=True)

    assert "SEC" not in result, "partial secret prefix must be stripped"
    assert OUTPUT_TRUNCATION_MARKER in result, "truncation marker must be preserved"
    assert result == "normal output " + OUTPUT_TRUNCATION_MARKER


def test_redact_partial_secret_at_boundary_stderr():
    """Same boundary guard applies to stderr (redact() is stream-agnostic)."""
    store = SecretStore()
    store.register("tok", "MY_TOKEN")

    text = "stderr line MY_T" + OUTPUT_TRUNCATION_MARKER

    result = store.redact(text, truncated=True)

    assert "MY_T" not in result, "partial secret prefix in stderr must be stripped"
    assert OUTPUT_TRUNCATION_MARKER in result


def test_redact_full_secret_immediately_before_marker():
    """A complete secret immediately before the marker is caught by full replacement."""
    store = SecretStore()
    store.register("key", "SECRETVALUE")

    text = "some outputSECRETVALUE" + OUTPUT_TRUNCATION_MARKER

    # Works even without truncated=True because full-secret replacement runs first.
    result = store.redact(text, truncated=True)

    assert "SECRETVALUE" not in result
    assert OUTPUT_TRUNCATION_MARKER in result


def test_redact_no_boundary_strip_without_flag():
    """Without truncated=True, a secret prefix ending a non-truncated body is NOT stripped.

    This is correct behaviour: the output was not truncated, so "SEC" at the
    end is legitimate content that happens to share characters with a secret.
    redact() must not remove it.
    """
    store = SecretStore()
    store.register("key", "SECRETVALUE")

    # No truncation marker — this is a plain string ending with "SEC".
    text = "the report covers SEC regulations"
    result = store.redact(text)
    assert result == text, "non-truncated output ending with a secret prefix must be unchanged"


def test_redact_marker_in_output_without_flag_is_safe():
    """A process can write the marker string itself; without truncated=True no strip occurs.

    This is the core reason for the explicit flag: marker sniffing would
    incorrectly treat this as truncated output and might strip legitimate tail
    content.  With the explicit flag approach, redact() leaves this unchanged.
    """
    store = SecretStore()
    store.register("key", "SECRETVALUE")

    # Simulate a process that deliberately printed the marker string followed
    # by the start of a secret, but this output was NOT actually truncated.
    crafted = "legit line" + OUTPUT_TRUNCATION_MARKER + "SEC"
    result = store.redact(crafted)  # truncated=False (default)
    # "SEC" at the very end was not stripped because truncated=False.
    assert result == crafted


def test_redact_only_longest_prefix_stripped_single_strip():
    """When multiple secrets share a prefix at the boundary, only the longest is stripped.

    Secrets: "ABCDEF" (prefix "ABC" len 3) and "ABCXYZ" (prefix "ABCX" len 4).
    Body ends with "ABCX".  The longest matching prefix is "ABCX" (4 chars).
    Only those 4 characters should be removed — not 7 (3+4).
    """
    store = SecretStore()
    store.register("s1", "ABCDEF")
    store.register("s2", "ABCXYZ")

    body = "safe content ABCX"
    text = body + OUTPUT_TRUNCATION_MARKER

    result = store.redact(text, truncated=True)

    # The 4-char prefix "ABCX" is stripped; "safe content " survives.
    assert "ABCX" not in result
    assert "safe content " in result
    assert OUTPUT_TRUNCATION_MARKER in result
    # Confirm no double-strip: body before the matched prefix is intact.
    assert result == "safe content " + OUTPUT_TRUNCATION_MARKER


def test_redact_safe_truncated_output_no_prefix_match():
    """Truncated output whose tail shares nothing with any secret is unchanged."""
    store = SecretStore()
    store.register("key", "SECRETVALUE")

    text = "safe output line" + OUTPUT_TRUNCATION_MARKER
    result = store.redact(text, truncated=True)

    assert result == text


def test_redact_empty_store_returns_text_unchanged():
    """redact() with no registered secrets must return the original text."""
    store = SecretStore()
    text = "no secrets here" + OUTPUT_TRUNCATION_MARKER
    assert store.redact(text, truncated=True) == text


def test_redact_empty_text_returns_empty():
    """redact() on an empty string must return an empty string."""
    store = SecretStore()
    store.register("key", "SECRETVALUE")
    assert store.redact("") == ""


# ---------------------------------------------------------------------------
# Phase 3 regression — manager.py forwards truncation_status correctly
# ---------------------------------------------------------------------------


def test_manager_forwards_truncation_flag_to_redact(tmp_path):
    """manager.execute() must pass truncation_status to redact() so that
    boundary stripping only fires on truly truncated streams.
    """
    from velix_agent.sandbox.backends.base import SandboxBackend
    from velix_agent.sandbox.result import SandboxResult

    secret = "BOUNDARY_SECRET"

    class MockTruncatedBackend(SandboxBackend):
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
            # Simulate truncated stdout: body ends with first 8 chars of secret.
            truncated_stdout = "output " + secret[:8] + OUTPUT_TRUNCATION_MARKER
            return SandboxResult(
                stdout=truncated_stdout,
                stderr="clean stderr",
                exit_code=0,
                command=command,
                truncation_status={"stdout": True, "stderr": False},
            )

    manager = SandboxManager(_force_none=True)
    manager.backend = MockTruncatedBackend()

    res = manager.execute(
        command=["echo", "x"],
        workspace_root=tmp_path,
        secrets={"S": secret},
    )

    # The partial prefix of the secret must not appear in the result.
    assert secret[:8] not in res.stdout, (
        "partial secret prefix must be stripped from truncated stdout"
    )
    assert OUTPUT_TRUNCATION_MARKER in res.stdout, "truncation marker must be preserved"
    # stderr was not truncated; "clean stderr" must be intact.
    assert res.stderr == "clean stderr"
