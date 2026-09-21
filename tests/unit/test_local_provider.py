"""Tests for Local/Ollama Provider."""

import json
import urllib.error
from unittest.mock import MagicMock

import pytest

from velix_agent.core.message import DocumentPart, Message
from velix_agent.providers.errors import (
    ProviderAPIError,
    ProviderTransientError,
    ProviderUnsupportedError,
)
from velix_agent.providers.local import LocalProvider


def test_local_provider_availability_running_model_exists(monkeypatch):
    provider = LocalProvider(model="llama3")

    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps(
        {"models": [{"name": "llama3:latest"}, {"name": "mistral"}]}
    ).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    mock_urlopen = MagicMock(return_value=mock_response)
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    is_avail, reason = provider.check_availability()
    assert is_avail is True
    assert reason == "available"


def test_local_provider_availability_missing_model(monkeypatch):
    provider = LocalProvider(model="llama3")

    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps({"models": [{"name": "mistral:latest"}]}).encode(
        "utf-8"
    )
    mock_response.__enter__.return_value = mock_response

    mock_urlopen = MagicMock(return_value=mock_response)
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    is_avail, reason = provider.check_availability()
    assert is_avail is False
    assert reason == "model not installed"


def test_local_provider_availability_not_running(monkeypatch):
    provider = LocalProvider(model="llama3")

    def mock_urlopen_error(*args, **kwargs):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_error)

    is_avail, reason = provider.check_availability()
    assert is_avail is False
    assert reason == "Ollama not running"


def test_local_provider_generate_success(monkeypatch):
    provider = LocalProvider(model="llama3")

    # Mock check_availability to be True
    monkeypatch.setattr(provider, "check_availability", lambda: (True, "available"))

    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps({"message": {"content": "4"}}).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    mock_urlopen = MagicMock(return_value=mock_response)
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    msg = Message(role="user", content="What is 2 + 2?")
    res = provider.generate([msg])

    assert res.status == "success"
    assert res.text == "4"


def test_local_provider_generate_not_running(monkeypatch):
    provider = LocalProvider(model="llama3")
    monkeypatch.setattr(provider, "check_availability", lambda: (False, "Ollama not running"))

    msg = Message(role="user", content="What is 2 + 2?")
    with pytest.raises(ProviderTransientError, match="Ollama not running"):
        provider.generate([msg])


def test_local_provider_generate_model_missing(monkeypatch):
    provider = LocalProvider(model="llama3")
    monkeypatch.setattr(provider, "check_availability", lambda: (False, "model not installed"))

    msg = Message(role="user", content="What is 2 + 2?")
    with pytest.raises(ProviderAPIError, match="model not installed"):
        provider.generate([msg])


def test_local_provider_multimodal_unsupported(monkeypatch):
    provider = LocalProvider()
    monkeypatch.setattr(provider, "check_availability", lambda: (True, "available"))
    msg = Message(role="user", content=[DocumentPart(mime_type="application/pdf", data=b"pdf")])
    with pytest.raises(ProviderUnsupportedError, match="does not support this file type"):
        provider.generate([msg])
