"""Models for the Orchestrator control layer."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional

from velix_agent.analysis.models import AnalysisResult


class OrchestratorState(StrEnum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    ANALYZING = "ANALYZING"
    RETRYING = "RETRYING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class StepExecutionResult:
    step_id: str
    analysis: Optional[AnalysisResult] = None
    output_context: str = ""
    error: Optional[str] = None


@dataclass
class OrchestratorContext:
    plan_id: str
    orchestrator_state: OrchestratorState = OrchestratorState.IDLE
    current_step_id: Optional[str] = None
    step_attempts: dict[str, int] = field(default_factory=dict)
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    blocked_steps: list[str] = field(default_factory=list)
    last_analysis: Optional[AnalysisResult] = None
    execution_history: list[StepExecutionResult] = field(default_factory=list)
