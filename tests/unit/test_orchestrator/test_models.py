"""Tests for Orchestrator models."""

from velix_agent.orchestrator.models import OrchestratorState


def test_orchestrator_states() -> None:
    assert OrchestratorState.IDLE == "IDLE"
    assert OrchestratorState.PLANNING == "PLANNING"
    assert OrchestratorState.READY == "READY"
    assert OrchestratorState.EXECUTING == "EXECUTING"
    assert OrchestratorState.ANALYZING == "ANALYZING"
    assert OrchestratorState.RETRYING == "RETRYING"
    assert OrchestratorState.BLOCKED == "BLOCKED"
    assert OrchestratorState.COMPLETED == "COMPLETED"
    assert OrchestratorState.FAILED == "FAILED"
    assert OrchestratorState.CANCELLED == "CANCELLED"
