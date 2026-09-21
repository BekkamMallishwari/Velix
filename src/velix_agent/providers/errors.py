"""Provider specific errors."""

from velix_agent.core.errors import VelixError


class ProviderError(VelixError):
    """Base exception for provider errors."""

    pass


class ProviderConfigError(ProviderError):
    """Raised when a provider is missing required configuration (e.g., API key)."""

    pass


class ProviderAPIError(ProviderError):
    """Raised when the provider API returns an error."""

    pass


class ProviderAuthError(ProviderAPIError):
    """Raised for authentication or invalid API key errors."""

    pass


class ProviderQuotaError(ProviderAPIError):
    """Raised when quota/billing is exhausted."""

    pass


class ProviderTransientError(ProviderAPIError):
    """Raised for rate limits, 503s, timeouts, or network errors that could be retried."""

    pass


class ProviderNotFoundError(ProviderAPIError):
    """Raised when the specified model is not found."""

    pass


class ProviderUnsupportedError(ProviderAPIError):
    """Raised when a multimodal input or feature is not supported by the provider."""

    pass


class ProviderAggregateError(ProviderError):
    """Raised when all configured providers have failed."""

    def __init__(self, message: str, errors: list[Exception] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []
