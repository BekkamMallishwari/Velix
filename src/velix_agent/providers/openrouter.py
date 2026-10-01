"""OpenRouter provider implementation."""

import base64
import json
import time
from typing import TYPE_CHECKING, Any

import openai

from velix_agent.core.message import (
    DocumentPart,
    ErrorPart,
    ImagePart,
    Message,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
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


class OpenRouterProvider(Provider):
    """Provider for OpenRouter models."""

    def __init__(
        self,
        api_key: str,
        model: str = "anthropic/claude-3.5-sonnet",
        fallback_model: str | None = None,
    ) -> None:
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
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
                    tool_calls = []
                    is_tool_result = False

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
                            raise ProviderUnsupportedError(
                                "OpenRouter provider does not support DocumentPart."
                            )
                        elif isinstance(part, ErrorPart):
                            parts.append({"type": "text", "text": f"[System Note: {part.error}]"})
                        elif isinstance(part, ToolCallPart):
                            if (
                                part.provider_metadata
                                and "openrouter_raw_tool_call" in part.provider_metadata
                            ):
                                tool_calls.append(
                                    part.provider_metadata["openrouter_raw_tool_call"]
                                )
                            else:
                                tool_calls.append(
                                    {
                                        "id": part.id or "call_unknown",
                                        "type": "function",
                                        "function": {
                                            "name": part.tool_name,
                                            "arguments": json.dumps(part.args),
                                        },
                                    }
                                )
                        elif isinstance(part, ToolResultPart):
                            is_tool_result = True
                            content_str = (
                                json.dumps(part.data)
                                if part.error is None
                                else json.dumps({"error": part.error})
                            )
                            openai_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": part.tool_call_id or "call_unknown",
                                    "content": content_str,
                                }
                            )

                    if not is_tool_result:
                        msg_dict: dict[str, Any] = {
                            "role": "user" if msg.role == "user" else "assistant",
                            "content": parts if parts else None,
                        }
                        if tool_calls and msg_dict["role"] == "assistant":
                            msg_dict["tool_calls"] = tool_calls
                            if not parts:
                                # When passing tool calls in assistant message, content can be None
                                # or empty string. OpenAI schema generally expects content None
                                msg_dict["content"] = None
                        openai_messages.append(msg_dict)
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

        openai_tools = []
        if tools:
            for tool in tools:
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                        },
                    }
                )

        for attempt in range(max_retries + 1):
            try:
                kwargs = {
                    "model": used_model,
                    "messages": openai_messages,
                }
                if openai_tools:
                    kwargs["tools"] = openai_tools

                response = self.client.chat.completions.create(**kwargs)  # type: ignore
                break
            except openai.AuthenticationError as e:
                raise ProviderAuthError("OpenRouter API Error: Authentication failed.") from e
            except openai.RateLimitError as e:
                if (
                    "quota" in str(e).lower()
                    or "billing" in str(e).lower()
                    or "balance" in str(e).lower()
                ):
                    raise ProviderQuotaError("OpenRouter API Error: Insufficient quota.") from e
                if attempt < max_retries:
                    time.sleep(base_delay * (2**attempt))
                    continue
                raise ProviderTransientError("OpenRouter API Error: Rate limited.") from e
            except openai.NotFoundError as e:
                if self.fallback_model and used_model != self.fallback_model:
                    used_model = self.fallback_model
                    try:
                        kwargs["model"] = used_model
                        response = self.client.chat.completions.create(**kwargs)  # type: ignore
                        break
                    except Exception as fallback_e:
                        raise ProviderAPIError(
                            "OpenRouter API Error: Fallback failed."
                        ) from fallback_e
                raise ProviderNotFoundError("OpenRouter API Error: Model not found.") from e
            except (openai.APIConnectionError, openai.InternalServerError) as e:
                if attempt < max_retries:
                    time.sleep(base_delay * (2**attempt))
                    continue
                raise ProviderTransientError(
                    "OpenRouter API Error: Temporary provider error."
                ) from e
            except openai.APIError as e:
                raise ProviderAPIError(
                    f"OpenRouter API Error: {e.message if hasattr(e, 'message') else str(e)}"
                ) from e
            except Exception as e:
                raise ProviderAPIError("OpenRouter API Error: Unexpected error.") from e

        if not response:
            raise ProviderAPIError("Failed to generate response")

        message = response.choices[0].message
        content = message.content or ""

        extracted_tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                # Store the raw tool call as a dict to ensure we can pass it back perfectly
                raw_dict = tc.model_dump(exclude_none=True)
                try:
                    args = json.loads(tc.function.arguments, strict=False)
                except Exception:
                    args = {}
                extracted_tool_calls.append(
                    ToolCallPart(
                        tool_name=tc.function.name,
                        args=args,
                        id=tc.id,
                        provider_metadata={"openrouter_raw_tool_call": raw_dict},
                    )
                )

        if not content and not extracted_tool_calls:
            raise ProviderAPIError(
                "OpenRouter returned an empty response with no content or tool calls."
            )

        metadata = {
            "provider": "openrouter",
            "model": used_model,
        }
        if response.usage:
            metadata["prompt_tokens"] = str(response.usage.prompt_tokens)
            metadata["completion_tokens"] = str(response.usage.completion_tokens)
            metadata["total_tokens"] = str(response.usage.total_tokens)

        return AgentResponse(
            text=content,
            status="success",
            metadata=metadata,
            tool_calls=extracted_tool_calls if extracted_tool_calls else None,
        )
