"""Tests for Model Provider Layer."""

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from velix_agent.core.config import VelixConfig
from velix_agent.core.message import Message
from velix_agent.providers.errors import ProviderConfigError
from velix_agent.providers.factory import get_provider
from velix_agent.providers.mock import MockProvider


def test_get_mock_provider() -> None:
    config = VelixConfig(default_provider="mock", default_model="test-mock")
    provider = get_provider(config)
    assert provider.primary is not None
    assert isinstance(provider.primary, MockProvider)
    assert provider.primary.model == "test-mock"


def test_missing_provider() -> None:
    config = VelixConfig(default_provider="unknown")
    with pytest.raises(ProviderConfigError, match="Unknown provider"):
        get_provider(config)


def test_missing_api_key() -> None:
    config = VelixConfig(default_provider="gemini", gemini_api_key=None)
    provider = get_provider(config)
    from velix_agent.providers.errors import ProviderAggregateError

    with pytest.raises(ProviderAggregateError, match="not configured"):
        provider.generate([])


def test_mock_provider_context() -> None:
    provider = MockProvider()

    # Empty
    res = provider.generate([])
    assert res.status == "error"

    # Generic
    msg = Message(role="user", content="hello")
    res = provider.generate([msg])
    assert "Hello" in res.text

    # Name memory
    msgs = [
        Message(role="user", content="My name is Alice"),
        Message(role="assistant", content="Nice to meet you!"),
        Message(role="user", content="What is my name?"),
    ]
    res = provider.generate(msgs)
    assert "Alice" in res.text


def test_config_loading_from_env(monkeypatch) -> None:
    monkeypatch.setenv("VELIX_GEMINI_API_KEY", "test-env-key")
    monkeypatch.setenv("VELIX_DEFAULT_PROVIDER", "gemini")

    config = VelixConfig()
    assert config.default_provider == "gemini"
    assert config.gemini_api_key is not None
    assert config.gemini_api_key.get_secret_value() == "test-env-key"


def test_gemini_provider_retry_success(monkeypatch) -> None:
    config = VelixConfig(default_provider="gemini", gemini_api_key=SecretStr("test-key"))

    mock_client_instance = MagicMock()
    mock_genai_client = MagicMock(return_value=mock_client_instance)
    monkeypatch.setattr("google.genai.Client", mock_genai_client)

    provider = get_provider(config)

    from google.genai.errors import APIError

    # First two calls fail with 503, third succeeds
    mock_response = MagicMock()
    mock_part = MagicMock()
    mock_part.function_call = None
    mock_part.text = "Success after retry"
    mock_content = MagicMock()
    mock_content.parts = [mock_part]
    mock_candidate = MagicMock()
    mock_candidate.content = mock_content
    mock_response.candidates = [mock_candidate]
    mock_response.usage_metadata.prompt_token_count = 5
    mock_response.usage_metadata.candidates_token_count = 5
    mock_response.usage_metadata.total_token_count = 10

    class MockAPIError(APIError):
        def __init__(self):
            self.code = 503

        def __str__(self):
            return "503 UNAVAILABLE"

    error_503 = MockAPIError()

    provider.primary.client.models.generate_content.side_effect = [
        error_503,
        error_503,
        mock_response,
    ]

    # Mock sleep to avoid waiting during tests
    monkeypatch.setattr("time.sleep", MagicMock())

    msg = Message(role="user", content="Hi")
    res = provider.generate([msg])

    assert res.text == "Success after retry"
    assert provider.primary.client.models.generate_content.call_count == 3


def test_gemini_provider_fallback(monkeypatch) -> None:
    config = VelixConfig(
        default_provider="gemini",
        default_model="gemini-3.7-flash",
        gemini_fallback_model="gemini-3.5-flash",
        gemini_api_key=SecretStr("test-key"),
    )

    mock_client_instance = MagicMock()
    mock_genai_client = MagicMock(return_value=mock_client_instance)
    monkeypatch.setattr("google.genai.Client", mock_genai_client)

    provider = get_provider(config)

    from google.genai.errors import APIError

    # All 4 regular attempts fail with 503. The 5th attempt (fallback) succeeds.
    mock_response = MagicMock()
    mock_part = MagicMock()
    mock_part.function_call = None
    mock_part.text = "Success on fallback"
    mock_content = MagicMock()
    mock_content.parts = [mock_part]
    mock_candidate = MagicMock()
    mock_candidate.content = mock_content
    mock_response.candidates = [mock_candidate]
    mock_response.usage_metadata.prompt_token_count = 5
    mock_response.usage_metadata.candidates_token_count = 5
    mock_response.usage_metadata.total_token_count = 10

    class MockAPIError(APIError):
        def __init__(self):
            self.code = 503

        def __str__(self):
            return "503 UNAVAILABLE"

    error_503 = MockAPIError()

    provider.primary.client.models.generate_content.side_effect = [
        error_503,
        error_503,
        error_503,
        error_503,
        mock_response,
    ]

    monkeypatch.setattr("time.sleep", MagicMock())

    msg = Message(role="user", content="Hi")
    res = provider.generate([msg])

    assert res.text == "Success on fallback"
    assert res.metadata["model"] == "gemini-3.5-flash"
    assert provider.primary.client.models.generate_content.call_count == 5


def test_gemini_provider_no_duplicate_fallback(monkeypatch) -> None:
    config = VelixConfig(
        default_provider="gemini",
        default_model="gemini-3.5-flash",
        gemini_fallback_model="gemini-3.5-flash",
        gemini_api_key=SecretStr("test-key"),
    )

    mock_client_instance = MagicMock()
    mock_genai_client = MagicMock(return_value=mock_client_instance)
    monkeypatch.setattr("google.genai.Client", mock_genai_client)

    provider = get_provider(config)

    from google.genai.errors import APIError

    # All 4 regular attempts fail with 503.
    # Since it's already gemini-3.5-flash, no 5th fallback attempt.
    class MockAPIError(APIError):
        def __init__(self):
            self.code = 503

        def __str__(self):
            return "503 UNAVAILABLE"

    error_503 = MockAPIError()

    provider.primary.client.models.generate_content.side_effect = [
        error_503,
        error_503,
        error_503,
        error_503,
    ]

    monkeypatch.setattr("time.sleep", MagicMock())

    import pytest

    from velix_agent.providers.errors import ProviderAggregateError

    msg = Message(role="user", content="Hi")
    with pytest.raises(ProviderAggregateError, match="timeout or temporary error"):
        provider.generate([msg])

    assert provider.primary.client.models.generate_content.call_count == 4


def test_gemini_multimodal_conversion(monkeypatch) -> None:
    config = VelixConfig(default_provider="gemini", gemini_api_key=SecretStr("test-key"))

    mock_client_instance = MagicMock()
    mock_genai_client = MagicMock(return_value=mock_client_instance)
    monkeypatch.setattr("google.genai.Client", mock_genai_client)

    provider = get_provider(config)

    mock_response = MagicMock()
    mock_response.text = "Multimodal success"
    provider.primary.client.models.generate_content.return_value = mock_response

    from velix_agent.core.message import DocumentPart, ErrorPart, ImagePart, TextPart

    parts = [
        TextPart(text="Look at this:"),
        ImagePart(mime_type="image/png", data=b"png-data"),
        DocumentPart(mime_type="application/pdf", data=b"pdf-data"),
        ErrorPart(error="Failed to load next part"),
    ]

    msg = Message(role="user", content=parts)
    provider.generate([msg])

    # Verify generate_content was called with correct types.Part conversions
    call_args = provider.primary.client.models.generate_content.call_args
    assert call_args is not None

    kwargs = call_args[1]
    contents = kwargs["contents"]

    # contents[0] is the message. contents[0].parts are the genai.types.Part objects
    assert len(contents) == 1
    genai_parts = contents[0].parts
    assert len(genai_parts) == 4

    from google.genai import types

    assert isinstance(genai_parts[0], types.Part)
    assert genai_parts[0].text == "Look at this:"

    assert genai_parts[1].inline_data.mime_type == "image/png"
    assert genai_parts[1].inline_data.data == b"png-data"

    assert genai_parts[2].inline_data.mime_type == "application/pdf"
    assert genai_parts[2].inline_data.data == b"pdf-data"

    assert genai_parts[3].text == "[System Note: Failed to load next part]"
