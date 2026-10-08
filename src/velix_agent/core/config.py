"""Strongly-typed configuration for VelixAgent.

Uses pydantic-settings so values can come from environment variables
(prefixed ``VELIX_``), a future configuration file, or application defaults.

Precedence (highest → lowest):
  1. Explicit CLI options (applied as overrides after loading)
  2. Environment variables
  3. Configuration file (future)
  4. Application defaults
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from velix_agent.utils.paths import get_default_history_file


class VelixConfig(BaseSettings):
    """Resolved application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="VELIX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Prioritize .env file over OS environment variables
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)

    # --- General -----------------------------------------------------------
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: str = Field(
        default="WARNING",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    max_input_file_size: int = Field(
        default=15 * 1024 * 1024,
        description="Maximum file size in bytes for multimodal inputs (default 15MB)",
    )
    max_tool_output_size: int = Field(
        default=8000,
        description=(
            "Maximum length of tool output strings "
            "(stdout, stderr, file content) to send to the provider."
        ),
    )

    # --- Memory ------------------------------------------------------------
    enable_memory: bool = Field(default=True, description="Enable SQLite-based memory system")

    # --- History -----------------------------------------------------------
    history_enabled: bool = Field(default=True, description="Enable persistent REPL history")
    history_file: Path = Field(
        default_factory=get_default_history_file,
        description="Path to the REPL history file",
    )

    # --- Model Providers ---------------------------------------------------
    default_provider: str = Field(default="gemini", description="Default model provider to use")
    default_model: str | None = Field(
        default="gemini-3.6-flash", description="Default model name to use"
    )
    gemini_fallback_model: str | None = Field(
        default=None, description="Optional fallback model if the primary Gemini model fails"
    )

    openai_api_key: SecretStr | None = Field(default=None, description="OpenAI API Key")
    openai_fallback_model: str | None = Field(
        default=None, description="Optional fallback model if the primary OpenAI model fails"
    )

    openrouter_api_key: SecretStr | None = Field(default=None, description="OpenRouter API Key")
    openrouter_fallback_model: str | None = Field(
        default=None, description="Optional fallback model if the primary OpenRouter model fails"
    )

    anthropic_api_key: SecretStr | None = Field(default=None, description="Anthropic API Key")
    gemini_api_key: SecretStr | None = Field(default=None, description="Google Gemini API Key")

    provider_chain: list[str] = Field(
        default_factory=lambda: ["gemini", "openai", "openrouter", "local"],
        description="Ordered list of provider names to form the fallback chain",
    )

    local_provider: str = Field(
        default="ollama", description="Local provider backend to use (e.g., ollama)"
    )
    local_model: str = Field(default="llama3", description="Local model name to use")
    local_base_url: str = Field(
        default="http://localhost:11434", description="Base URL for the local provider"
    )
