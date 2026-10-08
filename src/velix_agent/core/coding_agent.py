"""Coding Agent layer that bridges Orchestrator steps to the existing Agent execution."""

from typing import Any

from velix_agent.analysis.models import AnalysisResult, ResultClassification
from velix_agent.analysis.result_analyzer import ResultAnalyzer
from velix_agent.core.agent import Agent
from velix_agent.core.message import Message, TextPart, ToolResultPart
from velix_agent.orchestrator.models import StepExecutionResult
from velix_agent.planning.models import TaskStep
from velix_agent.sandbox.result import SandboxResult


class CodingAgent:
    """Executes a single TaskStep using the core Agent.

    Enforces strict execution boundaries: aborts immediately on tool error
    so the Orchestrator can handle retry logic.
    """

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    def execute_step(self, step: TaskStep) -> StepExecutionResult:
        """Execute one logical TaskStep. Returns a StepExecutionResult for the Orchestrator."""
        prompt = (
            f"Execute step: {step.title}\n"
            f"Description: {step.description}\n"
        )
        if hasattr(step, "retry_context") and step.retry_context:
            prompt += f"\nRETRY CONTEXT:\n{step.retry_context}\n"

        prompt += "\nWhen done, return a final text response indicating completion."
        parts: list[Any] = [TextPart(text=prompt)]
        self.agent._inject_project_memory(prompt, parts)
        new_messages: list[Message] = [Message(role="user", content=parts)]

        # MAX_STEPS bounds the internal loop, but we will abort early on any tool error.
        MAX_STEPS = 5

        for _ in range(MAX_STEPS):
            res = self.agent.execute_turn(new_messages)

            if res is not None:
                # LLM gave a final answer or hit an error
                if res.status == "error":
                    analysis = AnalysisResult(
                        classification=ResultClassification.UNKNOWN_FAILURE,
                        reason=res.error or "Agent returned error",
                        retryable=False,
                        security_blocked=False,
                        resource_limited=False,
                        timeout=False,
                        exit_code=1,
                    )
                    return StepExecutionResult(
                        step_id=step.step_id, analysis=analysis, error=res.error
                    )
                else:
                    analysis = AnalysisResult(
                        classification=ResultClassification.SUCCESS,
                        reason="Step completed successfully",
                        retryable=False,
                        security_blocked=False,
                        resource_limited=False,
                        timeout=False,
                        exit_code=0,
                    )
                    return StepExecutionResult(
                        step_id=step.step_id, analysis=analysis, output_context=res.text or ""
                    )

            # Check if tools were executed this turn
            last_msg = new_messages[-1]
            if last_msg.role == "user" and isinstance(last_msg.content, list):
                for part in last_msg.content:
                    if isinstance(part, ToolResultPart):
                        # Tool level error (e.g., Unknown tool, invalid args)
                        if part.error:
                            analysis = AnalysisResult(
                                classification=ResultClassification.RETRYABLE_FAILURE,
                                reason=part.error,
                                retryable=True,
                                security_blocked=False,
                                resource_limited=False,
                                timeout=False,
                                exit_code=1,
                            )
                            return StepExecutionResult(
                                step_id=step.step_id, analysis=analysis, error=part.error
                            )

                        # Check sandbox tool execution status
                        if part.tool_name == "run_command" and isinstance(part.data, dict):
                            sr = SandboxResult(
                                command=[],
                                exit_code=part.data.get("exit_code", 0),
                                stdout=part.data.get("stdout", ""),
                                stderr=part.data.get("stderr", ""),
                                duration=0.0,
                            )
                            analysis = ResultAnalyzer.analyze(sr)
                            if analysis.classification != ResultClassification.SUCCESS:
                                return StepExecutionResult(
                                    step_id=step.step_id,
                                    analysis=analysis,
                                    error=analysis.reason,
                                )

        # Exceeded internal iteration limit
        analysis = AnalysisResult(
            classification=ResultClassification.TIMEOUT,
            reason="Step execution exceeded internal iteration limit.",
            retryable=True,
            security_blocked=False,
            resource_limited=False,
            timeout=True,
            exit_code=-1,
        )
        return StepExecutionResult(step_id=step.step_id, analysis=analysis, error="Timeout")
