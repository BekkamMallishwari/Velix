import pytest

from velix_agent.core.config import VelixConfig


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("VELIX_DEFAULT_PROVIDER", "mock")
    monkeypatch.delenv("VELIX_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VELIX_ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch):
    # Ensure VelixConfig ignores the real .env file in tests
    original_init = VelixConfig.__init__

    def mocked_init(self, *args, **kwargs):
        if "_env_file" not in kwargs:
            kwargs["_env_file"] = None
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(VelixConfig, "__init__", mocked_init)
