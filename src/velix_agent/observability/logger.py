import collections

from velix_agent.observability.models import ExecutionEvent


class ObservabilityLogger:
    """In-memory bounded event collector."""

    def __init__(self, max_events: int = 1000):
        self.max_events = max_events
        # Deque automatically drops oldest events when maxlen is reached
        self.events: collections.deque[ExecutionEvent] = collections.deque(maxlen=self.max_events)

    def log_event(self, event: ExecutionEvent) -> None:
        self.events.append(event)

    def get_events_for_execution(self, execution_id: str) -> list[ExecutionEvent]:
        return [e for e in self.events if e.execution_id == execution_id]

    def get_all_events(self) -> list[ExecutionEvent]:
        return list(self.events)

    def clear(self) -> None:
        self.events.clear()
