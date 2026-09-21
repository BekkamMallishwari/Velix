from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from velix_agent.core.config import VelixConfig
from velix_agent.core.message import ImagePart, Message, TextPart
from velix_agent.providers.errors import ProviderAggregateError
from velix_agent.providers.factory import get_provider


def test_gemini_429_openai_succeeds(monkeypatch):
    config = VelixConfig(
        default_provider="gemini",
        gemini_api_key=SecretStr("gemini-key"),
        openai_api_key=SecretStr("openai-key"),
    )

    mock_genai_client = MagicMock()
    mock_openai_client = MagicMock()
    monkeypatch.setattr("google.genai.Client", MagicMock(return_value=mock_genai_client))
    monkeypatch.setattr("openai.OpenAI", MagicMock(return_value=mock_openai_client))

    provider = get_provider(config)

    from google.genai.errors import APIError

    class MockAPIError(APIError):
        def __init__(self):
            self.code = 429

        def __str__(self):
            return "429 RESOURCE_EXHAUSTED quota exhausted"

    mock_genai_client.models.generate_content.side_effect = MockAPIError()

    mock_openai_response = MagicMock()
    mock_openai_response.choices = [MagicMock(message=MagicMock(content="OpenAI Success"))]
    mock_openai_client.chat.completions.create.return_value = mock_openai_response

    msg = Message(role="user", content="Hi")
    res = provider.generate([msg])

    assert res.text == "OpenAI Success"
    assert mock_genai_client.models.generate_content.call_count == 1
    assert mock_openai_client.chat.completions.create.call_count == 1
    assert "Gemini unavailable (quota exhausted)" in res.metadata.get("fallback_warning", "")


def test_gemini_429_openai_fails(monkeypatch):
    config = VelixConfig(
        default_provider="gemini",
        gemini_api_key=SecretStr("gemini-key"),
        openai_api_key=SecretStr("openai-key"),
    )

    mock_genai_client = MagicMock()
    mock_openai_client = MagicMock()
    monkeypatch.setattr("google.genai.Client", MagicMock(return_value=mock_genai_client))
    monkeypatch.setattr("openai.OpenAI", MagicMock(return_value=mock_openai_client))

    provider = get_provider(config)

    from google.genai.errors import APIError

    class MockAPIError(APIError):
        def __init__(self):
            self.code = 429

        def __str__(self):
            return "429 RESOURCE_EXHAUSTED quota exhausted"

    mock_genai_client.models.generate_content.side_effect = MockAPIError()

    import openai

    mock_openai_client.chat.completions.create.side_effect = openai.APIError(
        "OpenAI down", request=MagicMock(), body=None
    )

    msg = Message(role="user", content="Hi")
    with pytest.raises(ProviderAggregateError) as exc_info:
        provider.generate([msg])

    assert "quota exhausted" in str(exc_info.value)
    assert "Openai: unavailable" in str(exc_info.value)


def test_gemini_cooldown_openai_used_next(monkeypatch):
    config = VelixConfig(
        default_provider="gemini",
        gemini_api_key=SecretStr("gemini-key"),
        openai_api_key=SecretStr("openai-key"),
    )

    mock_genai_client = MagicMock()
    mock_openai_client = MagicMock()
    monkeypatch.setattr("google.genai.Client", MagicMock(return_value=mock_genai_client))
    monkeypatch.setattr("openai.OpenAI", MagicMock(return_value=mock_openai_client))

    provider = get_provider(config)

    from google.genai.errors import APIError

    class MockAPIError(APIError):
        def __init__(self):
            self.code = 429

        def __str__(self):
            return "429 RESOURCE_EXHAUSTED quota exhausted"

    mock_genai_client.models.generate_content.side_effect = MockAPIError()

    mock_openai_response = MagicMock()
    mock_openai_response.choices = [MagicMock(message=MagicMock(content="OpenAI Success"))]
    mock_openai_client.chat.completions.create.return_value = mock_openai_response

    # First request
    provider.generate([Message(role="user", content="First")])
    assert mock_genai_client.models.generate_content.call_count == 1
    assert mock_openai_client.chat.completions.create.call_count == 1

    # Second request
    provider.generate([Message(role="user", content="Second")])
    # Gemini shouldn't be called again
    assert mock_genai_client.models.generate_content.call_count == 1
    assert mock_openai_client.chat.completions.create.call_count == 2


def test_multimodal_survives_fallback(monkeypatch):
    config = VelixConfig(
        default_provider="gemini",
        gemini_api_key=SecretStr("gemini-key"),
        openai_api_key=SecretStr("openai-key"),
    )

    mock_genai_client = MagicMock()
    mock_openai_client = MagicMock()
    monkeypatch.setattr("google.genai.Client", MagicMock(return_value=mock_genai_client))
    monkeypatch.setattr("openai.OpenAI", MagicMock(return_value=mock_openai_client))

    provider = get_provider(config)

    from google.genai.errors import APIError

    class MockAPIError(APIError):
        def __init__(self):
            self.code = 429

        def __str__(self):
            return "429 RESOURCE_EXHAUSTED quota exhausted"

    mock_genai_client.models.generate_content.side_effect = MockAPIError()

    mock_openai_response = MagicMock()
    mock_openai_response.choices = [
        MagicMock(message=MagicMock(content="OpenAI Multimodal Success"))
    ]
    mock_openai_client.chat.completions.create.return_value = mock_openai_response

    parts = [TextPart(text="Look at this:"), ImagePart(mime_type="image/png", data=b"png-data")]
    msg = Message(role="user", content=parts)

    res = provider.generate([msg])
    assert res.text == "OpenAI Multimodal Success"

    # Verify OpenAI got the multimodal payload
    call_args = mock_openai_client.chat.completions.create.call_args[1]
    msgs = call_args["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0]["content"], list)
    assert msgs[0]["content"][0]["type"] == "text"
    assert msgs[0]["content"][1]["type"] == "image_url"
