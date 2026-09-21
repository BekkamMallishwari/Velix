import pytest


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("VELIX_DEFAULT_PROVIDER", "mock")
    monkeypatch.delenv("VELIX_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VELIX_ANTHROPIC_API_KEY", raising=False)
