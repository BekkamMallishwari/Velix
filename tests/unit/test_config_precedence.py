from velix_agent.core.config import VelixConfig


def test_dotenv_takes_precedence_over_env(tmp_path, monkeypatch):
    # Set an OS environment variable
    monkeypatch.setenv("VELIX_DEFAULT_PROVIDER", "gemini")

    # Create a temporary .env file
    env_file = tmp_path / ".env"
    env_file.write_text("VELIX_DEFAULT_PROVIDER=openrouter\n")

    # Temporarily change directory to tmp_path so it finds the .env there,
    # OR we can just pass the path to VelixConfig
    config = VelixConfig(_env_file=env_file)

    assert config.default_provider == "openrouter"
