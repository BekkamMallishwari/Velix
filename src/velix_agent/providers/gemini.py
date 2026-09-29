"""Gemini provider implementation."""

import json
from typing import TYPE_CHECKING, Any

import google.genai
from google.genai import types

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
)


def _build_function_declaration(tool: "Tool") -> types.FunctionDeclaration:
    """Convert a Tool into a Gemini FunctionDeclaration.

    Uses ``tool.parameters`` (a JSON-schema dict) to build the parameter
    schema that Gemini expects.
    """
    params = tool.parameters  # e.g. {"type": "object", "properties": {...}, "required": [...]}

    properties: dict[str, types.Schema] = {}
    for prop_name, prop_schema in params.get("properties", {}).items():
        # Map JSON schema type strings to Gemini Schema type strings (uppercase)
        json_type = prop_schema.get("type", "string").upper()
        # Handle array type with items
        if json_type == "ARRAY":
            item_type = prop_schema.get("items", {}).get("type", "string").upper()
            properties[prop_name] = types.Schema(
                type=json_type,
                items=types.Schema(type=item_type),
                description=prop_schema.get("description", ""),
            )
        else:
            properties[prop_name] = types.Schema(
                type=json_type,
                description=prop_schema.get("description", ""),
            )

    gemini_params = types.Schema(
        type="OBJECT",
        properties=properties,
        required=params.get("required", []),
    )

    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description,
        parameters=gemini_params,
    )


def _tool_result_to_response_value(data: Any, error: str | None) -> dict[str, Any]:
    """Serialise a ToolResultPart payload into a dict for Gemini function_response."""
    if error is not None:
        return {"error": error}
    # Gemini often expects the response dictionary to contain a 'result' key.
    # We wrap the data inside {"result": ...} consistently.
    if isinstance(data, dict):
        return {"result": data}
    return {"result": json.dumps(data) if data is not None else ""}


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

    def generate(
        self, messages: list[Message], tools: list["Tool"] | None = None
    ) -> AgentResponse:
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
                gemini_role = "user" if msg.role == "user" else "model"
                parts: list[types.Part] = []

                if isinstance(msg.content, list):
                    for part in msg.content:
                        if isinstance(part, TextPart):
                            parts.append(types.Part.from_text(text=part.text))
                        elif isinstance(part, (ImagePart, DocumentPart)):
                            parts.append(
                                types.Part.from_bytes(data=part.data, mime_type=part.mime_type)
                            )
                        elif isinstance(part, ErrorPart):
                            parts.append(
                                types.Part.from_text(text=f"[System Note: {part.error}]")
                            )
                        elif isinstance(part, ToolCallPart):
                            # Assistant requested a tool call — replay as function_call part.
                            fc = types.FunctionCall(
                                name=part.tool_name,
                                args=part.args,
                                id=part.id
                            )
                            part_kwargs = {"function_call": fc}
                            if getattr(part, "thought_signature", None) is not None:
                                part_kwargs["thought_signature"] = part.thought_signature
                            parts.append(types.Part(**part_kwargs))
                        elif isinstance(part, ToolResultPart):
                            # Tool result — replay as function_response part.
                            response_value = _tool_result_to_response_value(
                                part.data, part.error
                            )
                            fr = types.FunctionResponse(
                                name=part.tool_name,
                                response=response_value,
                                id=part.tool_call_id
                            )
                            parts.append(types.Part(function_response=fr))
                else:
                    parts.append(types.Part.from_text(text=msg.content))

                if parts:
                    gemini_messages.append(
                        types.Content(role=gemini_role, parts=parts)
                    )

        # Build config — disable automatic function calling so we drive the loop.
        config = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )
        if system_instruction:
            config.system_instruction = system_instruction

        # Attach tool declarations if tools were provided.
        if tools:
            function_declarations = [_build_function_declaration(t) for t in tools]
            config.tools = [types.Tool(function_declarations=function_declarations)]

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
                    raise ProviderAPIError(f"Gemini API Error: Bad request. Details: {e}") from e

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

        tool_calls: list[ToolCallPart] | None = None
        content = ""

        # Manually parse candidates to avoid SDK warnings when non-text parts exist.
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            extracted_tool_calls = []
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    extracted_tool_calls.append(
                        ToolCallPart(
                            tool_name=part.function_call.name,
                            args=dict(part.function_call.args) if part.function_call.args else {},
                            id=part.function_call.id,
                            thought_signature=getattr(part, "thought_signature", None)
                        )
                    )
                if isinstance(part.text, str):
                    content += part.text

            if extracted_tool_calls:
                tool_calls = extracted_tool_calls

        metadata: dict[str, str] = {
            "provider": "gemini",
            "model": used_model,
        }
        if response.usage_metadata:
            metadata["prompt_tokens"] = str(response.usage_metadata.prompt_token_count)
            metadata["completion_tokens"] = str(response.usage_metadata.candidates_token_count)
            metadata["total_tokens"] = str(response.usage_metadata.total_token_count)

        return AgentResponse(
            text=content,
            status="success",
            metadata=metadata,
            tool_calls=tool_calls,
        )
