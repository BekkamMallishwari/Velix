"""Gemini provider implementation."""

import google.genai
from google.genai import types

from velix_agent.core.message import DocumentPart, ErrorPart, ImagePart, Message, TextPart
from velix_agent.core.response import AgentResponse
from velix_agent.providers.base import Provider
from velix_agent.providers.errors import (
    ProviderAPIError,
    ProviderAuthError,
    ProviderNotFoundError,
    ProviderQuotaError,
    ProviderTransientError,
)


class GeminiProvider(Provider):
    """Provider for Google Gemini models."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.6-flash",
        fallback_model: str | None = None,
    ) -> None:
        self.client = google.genai.Client(api_key=api_key)
        self.model = model
        self.fallback_model = fallback_model

    def generate(self, messages: list[Message]) -> AgentResponse:
        system_instruction = None
        gemini_messages: list[types.Content] = []

        for msg in messages:
            if msg.role == "system":
                if isinstance(msg.content, list):
                    text_parts = [p.text for p in msg.content if isinstance(p, TextPart)]
                    content_str = "\n".join(text_parts)
                else:
                    content_str = msg.content

                if not system_instruction:
                    system_instruction = content_str
                else:
                    system_instruction += "\n\n" + content_str
            else:
                parts = []
                if isinstance(msg.content, list):
                    for part in msg.content:
                        if isinstance(part, TextPart):
                            parts.append(types.Part.from_text(text=part.text))
                        elif isinstance(part, (ImagePart, DocumentPart)):
                            parts.append(
                                types.Part.from_bytes(data=part.data, mime_type=part.mime_type)
                            )
                        elif isinstance(part, ErrorPart):
                            parts.append(types.Part.from_text(text=f"[System Note: {part.error}]"))
                else:
                    parts.append(types.Part.from_text(text=msg.content))

                gemini_messages.append(
                    types.Content(
                        role="user" if msg.role == "user" else "model",
                        parts=parts,
                    )
                )

        config = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )
        if system_instruction:
            config.system_instruction = system_instruction

        import time

        from google.genai import errors

        max_retries = 3
        base_delay = 1.0
        used_model = self.model
        response = None

        for attempt in range(max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=used_model,
                    contents=gemini_messages,  # type: ignore[arg-type]
                    config=config,
                )
                break
            except errors.APIError as e:
                code = getattr(e, "code", None)
                msg_str = str(e).lower()
                is_503 = code == 503 or "503" in msg_str
                is_429 = code == 429 or "429" in msg_str
                is_404 = code == 404 or "404" in msg_str
                is_400_401_403 = code in (400, 401, 403) or any(
                    c in msg_str for c in ("400", "401", "403")
                )

                if is_400_401_403:
                    if code in (401, 403) or "401" in msg_str or "403" in msg_str:
                        raise ProviderAuthError("Gemini API Error: Authentication failed.") from e
                    raise ProviderAPIError("Gemini API Error: Bad request.") from e

                if is_503 or is_404:
                    if is_503 and attempt < max_retries:
                        time.sleep(base_delay * (2**attempt))
                        continue
                    elif self.fallback_model and used_model != self.fallback_model:
                        used_model = self.fallback_model
                        try:
                            response = self.client.models.generate_content(
                                model=used_model,
                                contents=gemini_messages,  # type: ignore[arg-type]
                                config=config,
                            )
                            break
                        except Exception as fallback_e:
                            raise ProviderAPIError(str(fallback_e)) from fallback_e
                    elif is_404:
                        raise ProviderNotFoundError("Gemini API Error: Model not found.") from e
                    else:
                        raise ProviderTransientError(
                            "Gemini API Error: Temporary provider error."
                        ) from e

                elif is_429:
                    if "quota" in msg_str or "credit" in msg_str:
                        raise ProviderQuotaError("Gemini API Error: Insufficient quota.") from e
                    if attempt < max_retries:
                        time.sleep(base_delay * (2**attempt))
                        continue
                    raise ProviderTransientError("Gemini API Error: Rate limited.") from e

                raise ProviderAPIError("Gemini API Error: Unknown API error.") from e
            except Exception as e:
                raise ProviderAPIError("Gemini API Error: Unexpected error.") from e

        if not response:
            raise ProviderAPIError("Failed to generate response")

        content = response.text or ""

        metadata = {
            "provider": "gemini",
            "model": used_model,
        }
        if response.usage_metadata:
            metadata["prompt_tokens"] = str(response.usage_metadata.prompt_token_count)
            metadata["completion_tokens"] = str(response.usage_metadata.candidates_token_count)
            metadata["total_tokens"] = str(response.usage_metadata.total_token_count)

        return AgentResponse(text=content, status="success", metadata=metadata)
