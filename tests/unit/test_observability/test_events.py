from velix_agent.observability.events import extract_events_from_result
from velix_agent.observability.models import EventType
from velix_agent.sandbox.result import SandboxResult


def test_extract_timeout():
    res = SandboxResult(
        stdout="",
        stderr="timed out after 5 seconds",
        exit_code=-1,
        command=["sleep", "10"],
        execution_id="test_exec",
        duration=5.0,
    )
    events = extract_events_from_result(res)
    assert any(e.event_type == EventType.TIMEOUT for e in events)
    assert any(e.event_type == EventType.EXECUTION_FAILED for e in events)


def test_extract_security_violation():
    res = SandboxResult(
        stdout="",
        stderr="permission denied",
        exit_code=1,
        command=["cat", "/etc/passwd"],
        execution_id="test_exec",
        security_events=["Blocked read access to /etc/passwd"],
    )
    events = extract_events_from_result(res)
    sec_events = [e for e in events if e.event_type == EventType.SECURITY_VIOLATION]
    assert len(sec_events) == 1
    assert sec_events[0].metadata["detail"] == "Blocked read access to /etc/passwd"
    assert any(e.event_type == EventType.EXECUTION_FAILED for e in events)


def test_extract_success():
    res = SandboxResult(
        stdout="hello",
        stderr="",
        exit_code=0,
        command=["echo", "hello"],
        execution_id="test_exec",
    )
    events = extract_events_from_result(res)
    assert any(e.event_type == EventType.EXECUTION_COMPLETED for e in events)
    assert not any(e.event_type == EventType.EXECUTION_FAILED for e in events)
