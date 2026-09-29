"""Deterministic Mock Provider for tests and offline mode."""

import re
from typing import TYPE_CHECKING

from velix_agent.core.message import Message
from velix_agent.core.response import AgentResponse
from velix_agent.providers.base import Provider

if TYPE_CHECKING:
    from velix_agent.tools.base import Tool


class MockProvider(Provider):
    """Deterministic local Phase 3 response generator."""

    def __init__(self, model: str = "mock-model") -> None:
        self.model = model

    def generate(
        self, messages: list[Message], tools: list["Tool"] | None = None
    ) -> AgentResponse:
        if not messages:
            return AgentResponse(
                text="Please provide a valid request.",
                status="error",
                error="Empty messages list received.",
            )

        content = messages[-1].content
        if isinstance(content, list):
            from velix_agent.core.message import ErrorPart, TextPart, ToolResultPart
            results = [p for p in content if isinstance(p, ToolResultPart)]
            if results:
                res = results[-1]
                text = f"Tool failed: {res.error}" if res.error else f"Tool succeeded: {res.data}"
                return AgentResponse(text=text, metadata={"provider": "mock", "model": self.model})

            parts_text = []
            for p in content:
                if isinstance(p, TextPart):
                    parts_text.append(p.text)
                elif isinstance(p, ErrorPart):
                    parts_text.append(f"[Error: {p.error}]")
            raw_last_message = "".join(parts_text).strip()
            last_message = raw_last_message.lower()
        else:
            raw_last_message = content.strip()
            last_message = raw_last_message.lower()

        if raw_last_message.startswith("execute tool "):
            parts = raw_last_message.split(" ", 3)
            if len(parts) >= 4:
                tool_name = parts[2]
                arg_str = parts[3]
                args = {}
                matches = re.findall(r'(\w+)=("(?:[^"]*)"|[^,]+)', arg_str)
                for k, v in matches:
                    if v.startswith('"') and v.endswith('"'):
                        v = v[1:-1]
                    if "," in v:
                        v = v.split(",")
                    args[k] = v

                from velix_agent.core.message import ToolCallPart
                return AgentResponse(
                    text="Invoking tool...",
                    tool_calls=[ToolCallPart(tool_name=tool_name, args=args)],
                    metadata={"provider": "mock", "model": self.model},
                )

        # Check context for name if asked        # Check context for name if asked
        if "what is my name" in last_message:
            for msg in reversed(messages):
                if msg.role == "user":
                    content = msg.content
                    if isinstance(content, list):
                        from velix_agent.core.message import ErrorPart, TextPart

                        parts_text = []
                        for p in content:
                            if isinstance(p, TextPart):
                                parts_text.append(p.text)
                            elif isinstance(p, ErrorPart):
                                parts_text.append(f"[Error: {p.error}]")
                        msg_str = "\n".join(parts_text)
                    else:
                        msg_str = content
                    match = re.search(r"my name is (\w+)", msg_str, re.IGNORECASE)
                    if match:
                        name = match.group(1).capitalize()
                        return AgentResponse(
                            text=f"Your name is {name}.",
                            metadata={"provider": "mock", "model": self.model},
                        )

            return AgentResponse(
                text="I don't know your name yet.",
                metadata={"provider": "mock", "model": self.model},
            )

        # Static responses
        if "what is velixagent" in last_message:
            text = (
                "VelixAgent is an AI coding agent designed to "
                "understand software-development tasks and "
                "eventually reason, use tools, execute changes, "
                "and verify results."
            )
        elif "what phase are we in" in last_message:
            text = "We are currently in Phase 4 — Multimodal Input."
        elif "what can you do" in last_message:
            text = (
                "Right now, I am running in Phase 4 mode. "
                "I can process multimodal messages and route them to a mock provider, "
                "or real models if configured."
            )
        elif last_message == "help":
            text = "Type your request, or use slash commands like /help, /status, or /clear."
        elif last_message == "status":
            text = "VelixAgent is active in Phase 4 (Multimodal Input)."
        elif "hello" in last_message or "hi" in last_message:
            text = "Hello! VelixAgent is running in Phase 4 mode."
        else:
            text = (
                "VelixAgent Phase 4 is active.\n\n"
                "The Agent Core received your request successfully.\n\n"
                "You are currently using the Mock Provider."
            )

        return AgentResponse(text=text, metadata={"provider": "mock", "model": self.model})
