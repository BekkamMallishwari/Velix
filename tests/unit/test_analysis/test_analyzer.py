from velix_agent.analysis.models import ResultClassification
from velix_agent.analysis.result_analyzer import ResultAnalyzer
from velix_agent.sandbox.result import SandboxResult


def test_analyze_success() -> None:
    res = SandboxResult(stdout="ok", stderr="", exit_code=0, command=["echo"])
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.SUCCESS
    assert analysis.retryable is False
    assert analysis.security_blocked is False


def test_analyze_timeout() -> None:
    res = SandboxResult(stdout="", stderr="timed out after 10s", exit_code=-1, command=["sleep"])
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.TIMEOUT
    assert analysis.retryable is True
    assert analysis.timeout is True


def test_analyze_security_blocked() -> None:
    # Via stderr
    res1 = SandboxResult(stdout="", stderr="permission denied", exit_code=1, command=["cat"])
    analysis1 = ResultAnalyzer.analyze(res1)
    assert analysis1.classification == ResultClassification.SECURITY_BLOCKED
    assert analysis1.security_blocked is True
    assert analysis1.retryable is False

    # Via security events
    res2 = SandboxResult(
        stdout="", stderr="", exit_code=1, command=["cat"], security_events=["Blocked..."]
    )
    analysis2 = ResultAnalyzer.analyze(res2)
    assert analysis2.classification == ResultClassification.SECURITY_BLOCKED


def test_analyze_resource_limit() -> None:
    res = SandboxResult(stdout="", stderr="MemoryError", exit_code=1, command=["python"])
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.RESOURCE_LIMIT
    assert analysis.resource_limited is True

    # Via exit code 137 (SIGKILL / OOM)
    res_oom = SandboxResult(stdout="", stderr="", exit_code=137, command=["python"])
    analysis_oom = ResultAnalyzer.analyze(res_oom)
    assert analysis_oom.classification == ResultClassification.RESOURCE_LIMIT


def test_analyze_non_retryable() -> None:
    res = SandboxResult(
        stdout="", stderr="SyntaxError: invalid syntax", exit_code=1, command=["python"]
    )
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.NON_RETRYABLE_FAILURE
    assert analysis.retryable is False


def test_analyze_retryable() -> None:
    res = SandboxResult(stdout="", stderr="no such file or directory", exit_code=1, command=["cat"])
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.RETRYABLE_FAILURE
    assert analysis.retryable is True

    # Missing python module
    res_mod = SandboxResult(
        stdout="",
        stderr="ModuleNotFoundError: No module named 'requests'",
        exit_code=1,
        command=["python"],
    )
    analysis_mod = ResultAnalyzer.analyze(res_mod)
    assert analysis_mod.classification == ResultClassification.RETRYABLE_FAILURE
    assert analysis_mod.retryable is True


def test_analyze_unknown() -> None:
    res = SandboxResult(stdout="", stderr="something weird happened", exit_code=1, command=["cmd"])
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.UNKNOWN_FAILURE
    assert analysis.retryable is False


def test_analyze_success_with_unisolated_filesystem_event() -> None:
    """Exit code 0 with UNISOLATED_FILESYSTEM must remain SUCCESS."""
    event = (
        "UNISOLATED_FILESYSTEM: Filesystem isolation is UNSUPPORTED on Windows in BALANCED mode. "
        "Filesystem access is not confined to workspace_root '/workspace'. "
        "Commands may access any files permitted to the host user."
    )
    res = SandboxResult(
        stdout="hello",
        stderr="",
        exit_code=0,
        command=["echo", "hello"],
        security_events=[event],
    )
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.SUCCESS
    assert analysis.security_blocked is False


def test_analyze_exit_1_with_unisolated_filesystem_event_ordinary_failure() -> None:
    """Exit code 1 with UNISOLATED_FILESYSTEM must not be classified as SECURITY_BLOCKED."""
    event = (
        "UNISOLATED_FILESYSTEM: Filesystem isolation is UNSUPPORTED on Windows in BALANCED mode. "
        "Filesystem access is not confined to workspace_root '/workspace'. "
        "Commands may access any files permitted to the host user."
    )
    # Case A: Syntax error -> NON_RETRYABLE_FAILURE
    res_syntax = SandboxResult(
        stdout="",
        stderr="SyntaxError: invalid syntax",
        exit_code=1,
        command=["python", "test.py"],
        security_events=[event],
    )
    analysis_syntax = ResultAnalyzer.analyze(res_syntax)
    assert analysis_syntax.classification == ResultClassification.NON_RETRYABLE_FAILURE
    assert analysis_syntax.security_blocked is False

    # Case B: Missing file -> RETRYABLE_FAILURE
    res_missing = SandboxResult(
        stdout="",
        stderr="cat: not found: missing.txt",
        exit_code=1,
        command=["cat", "missing.txt"],
        security_events=[event],
    )
    analysis_missing = ResultAnalyzer.analyze(res_missing)
    assert analysis_missing.classification == ResultClassification.RETRYABLE_FAILURE
    assert analysis_missing.security_blocked is False

    # Case C: Generic failure -> UNKNOWN_FAILURE
    res_unknown = SandboxResult(
        stdout="",
        stderr="Process failed with exit code 1",
        exit_code=1,
        command=["run.sh"],
        security_events=[event],
    )
    analysis_unknown = ResultAnalyzer.analyze(res_unknown)
    assert analysis_unknown.classification == ResultClassification.UNKNOWN_FAILURE
    assert analysis_unknown.security_blocked is False


def test_analyze_genuine_security_event_blocked() -> None:
    """Genuine security violations must remain classified as SECURITY_BLOCKED."""
    res = SandboxResult(
        stdout="",
        stderr="",
        exit_code=1,
        command=["cat", "/etc/shadow"],
        security_events=["Blocked read access to /etc/shadow"],
    )
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.SECURITY_BLOCKED
    assert analysis.security_blocked is True


def test_analyze_unisolated_plus_genuine_security_event_blocked() -> None:
    """UNISOLATED_FILESYSTEM combined with a genuine security event must be SECURITY_BLOCKED."""
    event = (
        "UNISOLATED_FILESYSTEM: Filesystem isolation is UNSUPPORTED on Windows in BALANCED mode."
    )
    res = SandboxResult(
        stdout="",
        stderr="",
        exit_code=1,
        command=["cat", "/etc/shadow"],
        security_events=[event, "Blocked read access to /etc/shadow"],
    )
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.SECURITY_BLOCKED
    assert analysis.security_blocked is True
