from velix_agent.analysis.models import ResultClassification
from velix_agent.analysis.result_analyzer import ResultAnalyzer
from velix_agent.sandbox.result import SandboxResult


def test_analyze_success():
    res = SandboxResult(stdout="ok", stderr="", exit_code=0, command=["echo"])
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.SUCCESS
    assert analysis.retryable is False
    assert analysis.security_blocked is False


def test_analyze_timeout():
    res = SandboxResult(stdout="", stderr="timed out after 10s", exit_code=-1, command=["sleep"])
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.TIMEOUT
    assert analysis.retryable is True
    assert analysis.timeout is True


def test_analyze_security_blocked():
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


def test_analyze_resource_limit():
    res = SandboxResult(stdout="", stderr="MemoryError", exit_code=1, command=["python"])
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.RESOURCE_LIMIT
    assert analysis.resource_limited is True

    # Via exit code 137 (SIGKILL / OOM)
    res_oom = SandboxResult(stdout="", stderr="", exit_code=137, command=["python"])
    analysis_oom = ResultAnalyzer.analyze(res_oom)
    assert analysis_oom.classification == ResultClassification.RESOURCE_LIMIT


def test_analyze_non_retryable():
    res = SandboxResult(
        stdout="", stderr="SyntaxError: invalid syntax", exit_code=1, command=["python"]
    )
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.NON_RETRYABLE_FAILURE
    assert analysis.retryable is False


def test_analyze_retryable():
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


def test_analyze_unknown():
    res = SandboxResult(stdout="", stderr="something weird happened", exit_code=1, command=["cmd"])
    analysis = ResultAnalyzer.analyze(res)
    assert analysis.classification == ResultClassification.UNKNOWN_FAILURE
    assert analysis.retryable is False
