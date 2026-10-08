"""Task Planner implementation."""

import json
import re
from typing import Any

from velix_agent.core.message import Message, TextPart
from velix_agent.memory.store import MemoryManager
from velix_agent.planning.models import TaskPlan, TaskStep
from velix_agent.providers.base import Provider


class PlanningError(Exception):
    """Base exception for planning errors."""

    pass


class InvalidPlanError(PlanningError):
    """Raised when the generated plan is invalid or malformed."""

    pass


class CapabilityUnavailableError(PlanningError):
    """Raised when a required capability is explicitly unavailable."""

    pass


class TaskPlanner:
    """Generates execution plans from user requests without executing them."""

    def __init__(
        self,
        provider: Provider,
        memory_manager: MemoryManager | None = None,
        runtime_manager: Any | None = None,
        sandbox_manager: Any | None = None,
    ) -> None:
        self.provider = provider
        self.memory_manager = memory_manager
        self.runtime_manager = runtime_manager
        self.sandbox_manager = sandbox_manager

    def _build_context_prompt(self, user_request: str) -> str:
        prompt = "Create an execution plan for the following request.\n\n"
        prompt += f"USER REQUEST:\n{user_request}\n\n"

        if self.memory_manager:
            try:
                results = self.memory_manager.search(user_request, limit=3)
                facts = [r for r in results if r.get("memory_type") == "project_fact"]
                if facts:
                    prompt += "<project_historical_memory>\n"
                    for f in facts:
                        prompt += f"- {f['topic']}: {f['content']}\n"
                    prompt += "</project_historical_memory>\n\n"
            except Exception:
                pass  # Ignore memory failures for planning

        prompt += "<sandbox_capabilities>\n"
        if self.sandbox_manager:
            caps = self.sandbox_manager.get_capabilities()
            prompt += f"Filesystem Isolation: {caps.filesystem_isolation}\n"
            prompt += f"Network Isolation: {caps.network_isolation}\n"
        else:
            prompt += "Unknown\n"
        prompt += "</sandbox_capabilities>\n\n"

        prompt += "<runtime_capabilities>\n"
        if self.runtime_manager:
            runtimes = self.runtime_manager.detect_all(workspace_root=".")
            for name, info in runtimes.items():
                if info.status.name == "SUPPORTED":
                    prompt += f"{name}: available (v{info.version})\n"
                else:
                    prompt += f"{name}: unavailable\n"
        else:
            prompt += "Unknown\n"
        prompt += "</runtime_capabilities>\n\n"

        prompt += (
            "Respond strictly with a JSON object representing the plan.\n"
            "Format:\n"
            "{\n"
            '    "goal": "string (max 1000 chars)",\n'
            '    "steps": [\n'
            "        {\n"
            '            "step_id": "string",\n'
            '            "title": "string (max 200 chars)",\n'
            '            "description": "string (max 2000 chars)",\n'
            '            "dependencies": ["step_id1"],\n'
            '            "success_criteria": ["string"],\n'
            '            "failure_criteria": ["string"],\n'
            '            "required_capabilities": ["string"],\n'
            '            "context": "string"\n'
            "        }\n"
            "    ],\n"
            '    "constraints": ["string"],\n'
            '    "assumptions": ["string"]\n'
            "}\n"
        )
        return prompt

    def create_plan(self, user_request: str) -> TaskPlan:
        """Create a plan from a user request."""
        if not user_request.strip():
            raise InvalidPlanError("Empty request cannot be planned.")

        prompt = self._build_context_prompt(user_request)

        msg = Message(role="user", content=[TextPart(text=prompt)])
        response = self.provider.generate([msg], tools=[])

        if response.status == "error":
            raise PlanningError(f"Provider failed: {response.error}")

        text = response.text or ""

        parsed = None
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        try:
            parsed = json.loads(match.group(1)) if match else json.loads(text)
        except json.JSONDecodeError as e:
            raise InvalidPlanError("Failed to parse JSON plan from provider output.") from e

        if not isinstance(parsed, dict):
            raise InvalidPlanError("Plan must be a JSON object.")

        try:
            steps = []
            for s in parsed.get("steps", []):
                step = TaskStep(
                    step_id=s.get("step_id", ""),
                    title=s.get("title", ""),
                    description=s.get("description", ""),
                    dependencies=s.get("dependencies", []),
                    success_criteria=s.get("success_criteria", []),
                    failure_criteria=s.get("failure_criteria", []),
                    required_capabilities=s.get("required_capabilities", []),
                    context=s.get("context", ""),
                )
                steps.append(step)

            plan = TaskPlan(
                goal=parsed.get("goal", ""),
                steps=steps,
                constraints=parsed.get("constraints", []),
                assumptions=parsed.get("assumptions", []),
            )
            plan.validate()
            return plan
        except ValueError as e:
            raise InvalidPlanError(f"Plan validation failed: {e}") from e
