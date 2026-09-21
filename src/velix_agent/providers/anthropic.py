"""Anthropic provider implementation."""

import anthropic

from velix_agent.core.message import Message
from velix_agent.core.response import AgentResponse
from velix_agent.providers.base import Provider
from velix_agent.providers.errors import ProviderAPIError


class AnthropicProvider(Provider):
    """Provider for Anthropic models."""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-latest") -> None:
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def generate(self, messages: list[Message]) -> AgentResponse:
        system_instruction = ""
        anthropic_messages = []

        for msg in messages:
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

            if msg.role == "system":
                if not system_instruction:
                    system_instruction = msg_str
                else:
                    system_instruction += "\n\n" + msg_str
            else:
                anthropic_messages.append({"role": msg.role, "content": msg_str})

        try:
            kwargs = {
                "model": self.model,
                "messages": anthropic_messages,
                "max_tokens": 4096,
            }
            if system_instruction:
                kwargs["system"] = system_instruction

            response = self.client.messages.create(**kwargs)  # type: ignore

            response_text = response.content[0].text if response.content else ""
            usage = response.usage

            metadata = {
                "provider": "anthropic",
                "model": response.model,
            }
            if usage:
                metadata["prompt_tokens"] = str(usage.input_tokens)
                metadata["completion_tokens"] = str(usage.output_tokens)
                metadata["total_tokens"] = str(usage.input_tokens + usage.output_tokens)

            return AgentResponse(text=response_text, status="success", metadata=metadata)
        except anthropic.APIError as e:
            raise ProviderAPIError(f"Anthropic API Error: {e}") from e
        except Exception as e:
            raise ProviderAPIError(f"Unexpected Anthropic Error: {e}") from e
