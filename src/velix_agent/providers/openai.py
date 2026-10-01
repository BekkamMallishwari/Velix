"""OpenAI provider implementation."""

import base64
import time
from typing import TYPE_CHECKING, Any

import openai

from velix_agent.core.message import DocumentPart, ErrorPart, ImagePart, Message, TextPart
from velix_agent.core.response import AgentResponse
from velix_agent.providers.base import Provider

if TYPE_CHECKING:
    from velix_agent.tools.base import Tool
from velix_agent.providers.errors import (
    ProviderAPIError,
    ProviderAuthError,
    ProviderNotFoundError,
    ProviderQuotaError,
    ProviderTransientError,
    ProviderUnsupportedError,
)


class OpenAIProvider(Provider):
    """Provider for OpenAI models."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        fallback_model: str | None = None,
    ) -> None:
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model
        self.fallback_model = fallback_model

    def generate(self, messages: list[Message], tools: list["Tool"] | None = None) -> AgentResponse:
        openai_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                if isinstance(msg.content, list):
                    text_parts = [p.text for p in msg.content if isinstance(p, TextPart)]
                    content_str = "\n".join(text_parts)
                else:
                    content_str = msg.content
                openai_messages.append({"role": "system", "content": content_str})
            else:
                if isinstance(msg.content, list):
                    parts: list[dict[str, Any]] = []
                    for part in msg.content:
                        if isinstance(part, TextPart):
                            parts.append({"type": "text", "text": part.text})
                        elif isinstance(part, ImagePart):
                            b64_data = base64.b64encode(part.data).decode("utf-8")
                            parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{part.mime_type};base64,{b64_data}"
                                    },
                                }
                            )
                        elif isinstance(part, DocumentPart):
                            # OpenAI Vision API doesn't natively support DocumentPart directly.
                            raise ProviderUnsupportedError(
                                "OpenAI provider currently does not support DocumentPart directly."
                            )
                        elif isinstance(part, ErrorPart):
                            parts.append({"type": "text", "text": f"[System Note: {part.error}]"})
                    openai_messages.append(
                        {"role": "user" if msg.role == "user" else "assistant", "content": parts}
                    )
                else:
                    openai_messages.append(
                        {
                            "role": "user" if msg.role == "user" else "assistant",
                            "content": msg.content,
                        }
                    )

        max_retries = 3
        base_delay = 1.0
        used_model = self.model
        response = None

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=used_model,
                    messages=openai_messages,  # type: ignore[arg-type]
                )
                break
            except openai.AuthenticationError as e:
                raise ProviderAuthError("OpenAI API Error: Authentication failed.") from e
            except openai.RateLimitError as e:
                if "quota" in str(e).lower() or "billing" in str(e).lower():
                    raise ProviderQuotaError("OpenAI API Error: Insufficient quota.") from e
                if attempt < max_retries:
                    time.sleep(base_delay * (2**attempt))
                    continue
                raise ProviderTransientError("OpenAI API Error: Rate limited.") from e
            except openai.NotFoundError as e:
                if self.fallback_model and used_model != self.fallback_model:
                    used_model = self.fallback_model
                    try:
                        response = self.client.chat.completions.create(
                            model=used_model,
                            messages=openai_messages,  # type: ignore[arg-type]
                        )
                        break
                    except Exception as fallback_e:
                        raise ProviderAPIError("OpenAI API Error: Fallback failed.") from fallback_e
                raise ProviderNotFoundError("OpenAI API Error: Model not found.") from e
            except (openai.APIConnectionError, openai.InternalServerError) as e:
                if attempt < max_retries:
                    time.sleep(base_delay * (2**attempt))
                    continue
                raise ProviderTransientError("OpenAI API Error: Temporary provider error.") from e
            except openai.APIError as e:
                raise ProviderAPIError("OpenAI API Error: Unknown API error.") from e
            except Exception as e:
                raise ProviderAPIError("OpenAI API Error: Unexpected error.") from e

        if not response:
            raise ProviderAPIError("Failed to generate response")

        content = response.choices[0].message.content or ""

        metadata = {
            "provider": "openai",
            "model": used_model,
        }
        if response.usage:
            metadata["prompt_tokens"] = str(response.usage.prompt_tokens)
            metadata["completion_tokens"] = str(response.usage.completion_tokens)
            metadata["total_tokens"] = str(response.usage.total_tokens)

        return AgentResponse(text=content, status="success", metadata=metadata)
