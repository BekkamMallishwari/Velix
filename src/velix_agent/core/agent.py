"""Agent Core for Phase 2."""

from __future__ import annotations

from velix_agent.core.logging import get_logger
from velix_agent.core.response import AgentResponse
from velix_agent.core.session import Session
from velix_agent.providers.base import Provider
from velix_agent.tools.registry import ToolRegistry
from velix_agent.tools.base import ToolResult

logger = get_logger("agent")

def _truncate_string(s: str, max_size: int, keep_end: bool = False) -> str:
    """Truncates a string if it exceeds max_size, leaving a marker."""
    if len(s) <= max_size:
        return s

    trunc_msg = "\n...[Output truncated due to size limit]...\n"
    actual_max = max_size - len(trunc_msg)
    if actual_max <= 0:
        return trunc_msg

    if keep_end:
        return trunc_msg + s[-actual_max:]
    else:
        return s[:actual_max] + trunc_msg

def _truncate_tool_result(res: ToolResult, max_size: int) -> ToolResult:
    """Safely limits the size of fields in a ToolResult."""
    import copy

    if res.status == "error" and res.error:
        truncated_error = _truncate_string(res.error, max_size, keep_end=True)
        return ToolResult(status=res.status, data=res.data, error=truncated_error, metadata=res.metadata)
    elif res.data and isinstance(res.data, dict):
        # We must copy the dict to avoid modifying original frozen data references
        new_data = copy.deepcopy(res.data)
        changed = False
        # Truncate specific known fields that can be large
        if "content" in new_data and isinstance(new_data["content"], str):
            new_data["content"] = _truncate_string(new_data["content"], max_size, keep_end=False)
            changed = True
        if "stdout" in new_data and isinstance(new_data["stdout"], str):
            new_data["stdout"] = _truncate_string(new_data["stdout"], max_size, keep_end=False)
            changed = True
        if "stderr" in new_data and isinstance(new_data["stderr"], str):
            new_data["stderr"] = _truncate_string(new_data["stderr"], max_size, keep_end=True)
            changed = True
        if changed:
            return ToolResult(status=res.status, data=new_data, error=res.error, metadata=res.metadata)
    return res


class Agent:
    """The central Agent abstraction for VelixAgent.

    Responsible for processing user input, updating context, and returning responses.
    """

    def __init__(
        self,
        session: Session,
        provider: Provider | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.session = session
        self._provider = provider
        self.tool_registry = tool_registry or ToolRegistry()
        import os
        from pathlib import Path

        self.cwd = Path(os.getcwd())

    def respond(self, user_input: str) -> AgentResponse:
        """Process a user message and generate a response."""
        logger.debug("Agent received input: %s", user_input)

        if not user_input.strip():
            return AgentResponse(
                text="Please provide a valid request.",
                status="error",
                error="Empty input received.",
            )

        # 1. Parse input with InputRouter
        from velix_agent.core.config import VelixConfig
        from velix_agent.core.input_router import InputRouter

        config = VelixConfig()
        parts = InputRouter.parse(user_input, max_size=config.max_input_file_size, cwd=self.cwd)

        # Guard against uninitialized provider
        if self._provider is None:
            return AgentResponse(
                text="Provider is not configured.",
                status="error",
                error="Provider was not initialized in Agent.",
            )

        try:
            from velix_agent.core.message import Message, TextPart, ToolResultPart

            # We will accumulate messages generated in this turn
            new_messages: list[Message] = [Message(role="user", content=parts)]

            MAX_ITERATIONS = 5
            available_tools = self.tool_registry.list_tools()

            for _ in range(MAX_ITERATIONS):
                current_context = self.session.context.get_messages() + new_messages
                response = self._provider.generate(current_context, tools=available_tools)

                if response.status == "error" or not response.tool_calls:
                    # Final response reached
                    if response.status == "success":
                        # Add all accumulated messages to the session context
                        for msg in new_messages:
                            self.session.context.add_message(msg)
                        if response.text:
                            self.session.context.add_assistant_message(response.text)
                    return response

                # We have tool calls
                # Add the assistant's response with tool calls to new_messages
                assistant_parts = []
                if response.text:
                    assistant_parts.append(TextPart(text=response.text))

                # Safely handle tool_calls which is a list of ToolCallPart
                for tc in response.tool_calls:
                    assistant_parts.append(tc)
                new_messages.append(Message(role="assistant", content=assistant_parts))

                tool_results = []
                for tc in response.tool_calls:
                    tool = self.tool_registry.get_tool(tc.tool_name)
                    if tool is None:
                        tool_results.append(
                            ToolResultPart(
                                tool_name=tc.tool_name, error=f"Unknown tool: {tc.tool_name}", tool_call_id=tc.id
                            )
                        )
                        continue

                    try:
                        res = tool.execute(**tc.args)
                        res = _truncate_tool_result(res, config.max_tool_output_size)

                        if res.status == "error":
                            tool_results.append(
                                ToolResultPart(tool_name=tc.tool_name, error=res.error, tool_call_id=tc.id)
                            )
                        else:
                            tool_results.append(
                                ToolResultPart(tool_name=tc.tool_name, data=res.data, tool_call_id=tc.id)
                            )
                    except TypeError as e:
                        tool_results.append(
                            ToolResultPart(
                                tool_name=tc.tool_name, error=f"Invalid arguments: {e}", tool_call_id=tc.id
                            )
                        )
                    except Exception as e:
                        tool_results.append(
                            ToolResultPart(
                                tool_name=tc.tool_name, error=f"Execution error: {e}", tool_call_id=tc.id
                            )
                        )

                # Feed tool results back as a user message
                new_messages.append(Message(role="user", content=tool_results))

            # Exceeded MAX_ITERATIONS
            return AgentResponse(
                text="Agent exceeded maximum tool iterations.",
                status="error",
                error="Max iterations reached.",
            )

        except Exception as e:
            from velix_agent.providers.errors import ProviderError

            if isinstance(e, ProviderError):
                logger.error(f"Provider Error: {e}")
                return AgentResponse(
                    text=str(e),
                    status="error",
                    error=str(e),
                )
            else:
                logger.exception("Agent response generation failed")
                return AgentResponse(
                    text="An unexpected error occurred while generating a response.",
                    status="error",
                    error=str(e),
                )
