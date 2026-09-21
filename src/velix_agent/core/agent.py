"""Agent Core for Phase 2."""

from __future__ import annotations

from velix_agent.core.logging import get_logger
from velix_agent.core.response import AgentResponse
from velix_agent.core.session import Session
from velix_agent.providers.base import Provider

logger = get_logger("agent")


class Agent:
    """The central Agent abstraction for VelixAgent.

    Responsible for processing user input, updating context, and returning responses.
    """

    def __init__(self, session: Session, provider: Provider | None = None) -> None:
        self.session = session
        self._provider = provider
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
            # Construct temporary message list
            from velix_agent.core.message import Message

            current_messages = self.session.context.get_messages()
            temp_user_msg = Message(role="user", content=parts)

            # 2. Process request using full context
            response = self._provider.generate([*current_messages, temp_user_msg])

            # 3. Update context with user and assistant response
            if response.status == "success":
                self.session.context.add_user_message(parts)
                self.session.context.add_assistant_message(response.text)

            return response

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
