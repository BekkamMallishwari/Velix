from velix_agent.observability.models import EventType, ExecutionEvent
from velix_agent.sandbox.result import SandboxResult


def extract_events_from_result(result: SandboxResult) -> list[ExecutionEvent]:
    events: list[ExecutionEvent] = []

    is_timeout = result.exit_code == -1 and "timed out" in result.stderr.lower()

    if is_timeout:
        events.append(
            ExecutionEvent(
                event_type=EventType.TIMEOUT,
                execution_id=result.execution_id,
                backend=result.backend,
                command=result.command,
                duration=result.duration,
                exit_code=result.exit_code,
            )
        )

    for sec_event in result.security_events:
        events.append(
            ExecutionEvent(
                event_type=EventType.SECURITY_VIOLATION,
                metadata={"detail": sec_event},
                execution_id=result.execution_id,
                backend=result.backend,
                command=result.command,
                duration=result.duration,
                exit_code=result.exit_code,
            )
        )

    # Some basic resource limit inferences can be added here if the sandbox provides them
    # For now, rely on exit code for success/fail
    if result.exit_code == 0:
        events.append(
            ExecutionEvent(
                event_type=EventType.EXECUTION_COMPLETED,
                execution_id=result.execution_id,
                backend=result.backend,
                command=result.command,
                duration=result.duration,
                exit_code=result.exit_code,
            )
        )
    else:
        events.append(
            ExecutionEvent(
                event_type=EventType.EXECUTION_FAILED,
                execution_id=result.execution_id,
                backend=result.backend,
                command=result.command,
                duration=result.duration,
                exit_code=result.exit_code,
            )
        )

    return events
