"""Agent protection and safety components."""

import json
from typing import Any, Optional
import time
from dataclasses import dataclass

from velix_agent.core.message import Message, ToolCallPart

@dataclass
class ExecutionBudget:
    """A per-run execution budget passed down to enforce tool limits before execution."""
    max_tool_invocations: int = 50
    max_time_seconds: int = 900
    total_tool_calls: int = 0
    start_time: Optional[float] = None

    def __post_init__(self) -> None:
        if self.start_time is None:
            self.start_time = time.time()

    def is_time_exceeded(self) -> bool:
        if self.start_time is None:
            return False
        return (time.time() - self.start_time) > self.max_time_seconds

    def consume_tool(self) -> bool:
        """Attempt to consume one tool call from the budget. Returns False if exceeded."""
        if self.total_tool_calls >= self.max_tool_invocations:
            return False
        self.total_tool_calls += 1
        return True

class RepeatedActionDetector:
    """Detects when the LLM gets stuck calling the same tool with identical arguments."""

    @staticmethod
    def _normalize_args(args: dict[str, Any]) -> str:
        """Deterministically serialize arguments to a string for comparison."""
        try:
            return json.dumps(args, sort_keys=True)
        except Exception:
            # Fallback for non-serializable args. Use string representation, 
            # though it might not be deterministic for dict keys, it's a safe fallback.
            return str(args)

    @classmethod
    def check_repeated_calls(
        cls,
        messages: list[Message],
        target_call: ToolCallPart,
        limit: int = 3,
    ) -> bool:
        """Check if the given tool call has already been attempted `limit` or more times.

        Parameters
        ----------
        messages : list[Message]
            The conversation history for the current execution loop.
        target_call : ToolCallPart
            The pending tool call.
        limit : int, optional
            The number of allowed PREVIOUS identical calls. Default is 3.

        Returns
        -------
        bool
            True if the limit has been reached or exceeded, False otherwise.
        """
        if limit < 0:
            limit = 0

        target_norm = cls._normalize_args(target_call.args)
        count = 0

        for msg in messages:
            if msg.role == "assistant" and isinstance(msg.content, list):
                for part in msg.content:
                    if isinstance(part, ToolCallPart) and part.id != target_call.id:
                        if part.tool_name == target_call.tool_name:
                            part_norm = cls._normalize_args(part.args)
                            if part_norm == target_norm:
                                count += 1

        return count >= limit
