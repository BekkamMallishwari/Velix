import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(Enum):
    EXECUTION_STARTED = "execution_started"
    PROCESS_STARTED = "process_started"
    TOOL_CALLED = "tool_called"
    SECURITY_VIOLATION = "security_violation"
    RESOURCE_LIMIT = "resource_limit"
    TIMEOUT = "timeout"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"


@dataclass
class ExecutionEvent:
    execution_id: str
    event_type: EventType
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    backend: str | None = None
    command: list[str] | None = None
    duration: float | None = None
    exit_code: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
