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
class ExecutionLimits:
    max_total_attempts: int = 25
    max_tool_invocations: int = 50
    max_time_seconds: int = 900


@dataclass
class StepExecutionResult:
    step_id: str
    analysis: Optional[AnalysisResult] = None
    output_context: str = ""
    error: Optional[str] = None
    tool_call_count: int = 0


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
    total_step_attempts: int = 0
    total_tool_calls: int = 0
    start_time: Optional[float] = None
