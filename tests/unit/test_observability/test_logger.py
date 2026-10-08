from velix_agent.observability.logger import ObservabilityLogger
from velix_agent.observability.models import EventType, ExecutionEvent


def test_logger_bounded_storage():
    logger = ObservabilityLogger(max_events=3)

    logger.log_event(ExecutionEvent(execution_id="1", event_type=EventType.EXECUTION_STARTED))
    logger.log_event(ExecutionEvent(execution_id="2", event_type=EventType.EXECUTION_STARTED))
    logger.log_event(ExecutionEvent(execution_id="3", event_type=EventType.EXECUTION_STARTED))

    assert len(logger.get_all_events()) == 3

    # Adding a 4th event should drop the oldest (execution_id="1")
    logger.log_event(ExecutionEvent(execution_id="4", event_type=EventType.EXECUTION_STARTED))

    all_events = logger.get_all_events()
    assert len(all_events) == 3
    assert all_events[0].execution_id == "2"
    assert all_events[1].execution_id == "3"
    assert all_events[2].execution_id == "4"


def test_get_events_for_execution():
    logger = ObservabilityLogger()
    logger.log_event(ExecutionEvent(execution_id="1", event_type=EventType.EXECUTION_STARTED))
    logger.log_event(ExecutionEvent(execution_id="1", event_type=EventType.EXECUTION_COMPLETED))
    logger.log_event(ExecutionEvent(execution_id="2", event_type=EventType.EXECUTION_STARTED))

    exec_1_events = logger.get_events_for_execution("1")
    assert len(exec_1_events) == 2
    assert exec_1_events[0].event_type == EventType.EXECUTION_STARTED
    assert exec_1_events[1].event_type == EventType.EXECUTION_COMPLETED
