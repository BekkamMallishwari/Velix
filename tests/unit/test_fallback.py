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


def test_gemini_cooldown_expires_after_300s(monkeypatch):
    """Regression: Gemini becomes eligible again once the 300-s cooldown expires."""
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

    # Gemini always raises 429 throughout this test.
    mock_genai_client.models.generate_content.side_effect = MockAPIError()

    mock_openai_response = MagicMock()
    mock_openai_response.choices = [MagicMock(message=MagicMock(content="OpenAI Success"))]
    mock_openai_client.chat.completions.create.return_value = mock_openai_response

    # Use a mutable container so the nested lambda can advance simulated time.
    # manager.py does `import time` locally inside generate(), so we patch the
    # stdlib time module's `time` attribute directly.
    import time as _time_mod

    fake_time: list[float] = [1_000_000.0]
    monkeypatch.setattr(_time_mod, "time", lambda: fake_time[0])

    # ── Request 1 (t = 0 s) ──────────────────────────────────────────────────
    # Gemini is tried, raises 429, enters cooldown until t=1_000_300.
    # OpenAI handles the request.
    provider.generate([Message(role="user", content="First")])
    assert mock_genai_client.models.generate_content.call_count == 1, (
        "Gemini should have been attempted once on the first request"
    )
    assert mock_openai_client.chat.completions.create.call_count == 1, (
        "OpenAI should have been called once as the fallback"
    )

    # ── Request 2 (t = +100 s — still within cooldown) ───────────────────────
    # Gemini must be skipped; OpenAI call count grows to 2.
    fake_time[0] += 100.0  # now 1_000_100 < 1_000_300
    provider.generate([Message(role="user", content="Second")])
    assert mock_genai_client.models.generate_content.call_count == 1, (
        "Gemini must remain skipped while cooldown is active (t+100 s)"
    )
    assert mock_openai_client.chat.completions.create.call_count == 2, (
        "OpenAI should be the sole provider during cooldown"
    )

    # ── Request 3 (t = +300 s — cooldown just expired) ───────────────────────
    # Gemini is eligible again; it still raises 429, so OpenAI handles it.
    # Gemini call count becomes 2; OpenAI call count becomes 3.
    fake_time[0] = 1_000_000.0 + 300.0  # exactly at cooldown expiry
    provider.generate([Message(role="user", content="Third")])
    assert mock_genai_client.models.generate_content.call_count == 2, (
        "Gemini should be re-attempted once the 300-s cooldown has expired"
    )
    assert mock_openai_client.chat.completions.create.call_count == 3, (
        "OpenAI should handle the third request after Gemini fails again"
    )


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
