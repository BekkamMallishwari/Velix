"""Provider registry and factory."""

from typing import TYPE_CHECKING, Any

from velix_agent.core.config import VelixConfig
from velix_agent.providers.base import Provider

if TYPE_CHECKING:
    pass


def _get_secret(secret: Any) -> str:
    if secret is None:
        return ""
    if hasattr(secret, "get_secret_value"):
        return str(secret.get_secret_value())
    return str(secret)


def _create_provider_instance(
    name: str, config: VelixConfig, is_primary: bool = False
) -> Provider | None:
    name = name.strip().lower()

    # Only use config.default_model if this is the primary provider being instantiated
    def get_model(provider_default: str) -> str:
        if is_primary and config.default_model:
            return config.default_model
        return provider_default

    if name == "mock":
        from velix_agent.providers.mock import MockProvider

        return MockProvider(model=get_model("mock-model"))

    elif name == "gemini":
        api_key = _get_secret(config.gemini_api_key)
        if not api_key:
            return None
        from velix_agent.providers.gemini import GeminiProvider

        return GeminiProvider(
            api_key=api_key,
            model=get_model("gemini-3.6-flash"),
            fallback_model=config.gemini_fallback_model,
        )

    elif name == "anthropic":
        api_key = _get_secret(config.anthropic_api_key)
        if not api_key:
            return None
        from velix_agent.providers.anthropic import AnthropicProvider

        return AnthropicProvider(
            api_key=api_key,
            model=get_model("claude-3-5-sonnet-latest"),
        )

    elif name == "openai":
        api_key = _get_secret(config.openai_api_key)
        if not api_key:
            return None
        from velix_agent.providers.openai import OpenAIProvider

        return OpenAIProvider(
            api_key=api_key,
            model=get_model("gpt-4o"),
            fallback_model=config.openai_fallback_model,
        )

    elif name == "openrouter":
        api_key = _get_secret(config.openrouter_api_key)
        if not api_key:
            return None
        from velix_agent.providers.openrouter import OpenRouterProvider

        return OpenRouterProvider(
            api_key=api_key,
            model=get_model("anthropic/claude-3.5-sonnet"),
            fallback_model=config.openrouter_fallback_model,
        )

    elif name == "local":
        from velix_agent.providers.local import LocalProvider

        return LocalProvider(model=config.local_model, base_url=config.local_base_url)

    return None


def get_provider(config: VelixConfig) -> Provider:
    """Instantiate and return the configured provider manager."""
    from velix_agent.providers.errors import ProviderConfigError
    from velix_agent.providers.manager import ProviderManager

    primary_name = config.default_provider.strip().lower()

    if primary_name not in ("mock", "gemini", "anthropic", "openai", "openrouter", "local"):
        raise ProviderConfigError(f"Unknown provider configured: {primary_name}")

    primary = _create_provider_instance(primary_name, config, is_primary=True)

    fallbacks = []

    fallback_names = config.provider_chain
    if not fallback_names:
        fallback_names = []
        if primary_name != "openrouter" and config.openrouter_api_key:
            fallback_names.append("openrouter")
        if primary_name != "openai" and config.openai_api_key:
            fallback_names.append("openai")
        if primary_name != "anthropic" and config.anthropic_api_key:
            fallback_names.append("anthropic")
        if primary_name != "gemini" and config.gemini_api_key:
            fallback_names.append("gemini")
        if primary_name != "mock":
            # Don't auto-fallback to mock unless asked
            pass

    for fallback_name in fallback_names:
        fallback_name = fallback_name.strip().lower()
        if fallback_name == primary_name:
            continue
        fallback_provider = _create_provider_instance(fallback_name, config)
        if fallback_provider:
            fallbacks.append((fallback_name, fallback_provider))

    return ProviderManager(primary=primary, primary_name=primary_name, fallbacks=fallbacks)
