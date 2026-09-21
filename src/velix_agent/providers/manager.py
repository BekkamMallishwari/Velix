"""Provider manager implementation for fallbacks."""

from velix_agent.core.logging import get_logger
from velix_agent.core.message import Message
from velix_agent.core.response import AgentResponse
from velix_agent.providers.base import Provider
from velix_agent.providers.errors import (
    ProviderAggregateError,
    ProviderAuthError,
    ProviderNotFoundError,
    ProviderQuotaError,
    ProviderTransientError,
    ProviderUnsupportedError,
)

logger = get_logger("provider_manager")


class ProviderManager(Provider):
    """Manages provider execution and fallbacks."""

    def __init__(
        self, primary: Provider | None, primary_name: str, fallbacks: list[tuple[str, Provider]]
    ) -> None:
        self.primary = primary
        self.primary_name = primary_name
        self.fallbacks = fallbacks
        self.cooldowns: dict[str, float] = {}

    def generate(self, messages: list[Message]) -> AgentResponse:
        import time

        errors: list[Exception] = []
        error_msgs: list[str] = []
        fallback_warnings: list[str] = []

        providers_to_try = []
        if self.primary:
            providers_to_try.append((self.primary_name, self.primary))
        else:
            error_msgs.append(f"{self.primary_name}: not configured")

        providers_to_try.extend(self.fallbacks)

        current_time = time.time()

        for name, provider in providers_to_try:
            if name in self.cooldowns:
                if current_time < self.cooldowns[name]:
                    logger.debug("Skipping provider %s (on cooldown)", name)
                    error_msgs.append(f"{name}: temporarily unavailable (on cooldown)")
                    continue
                else:
                    del self.cooldowns[name]

            try:
                logger.debug("Attempting provider: %s", name)
                response = provider.generate(messages)
                if fallback_warnings:
                    final_warning = "Provider fallback:\n"
                    fallback_names = [*[n for n, _ in providers_to_try][1:], name]
                    for warn, fallback_name in zip(fallback_warnings, fallback_names, strict=False):
                        if warn == fallback_warnings[-1]:
                            final_warning += f"{warn}\n→ Switching to {name.capitalize()}...\n"
                        else:
                            fb = fallback_name.capitalize()
                            final_warning += f"{warn}\n→ Switching to {fb}...\n"
                    response.metadata["fallback_warning"] = final_warning.strip()
                return response
            except ProviderAuthError as e:
                self.cooldowns[name] = current_time + 300.0
                msg = "authentication/configuration error"
                errors.append(e)
                error_msgs.append(f"- {name.capitalize()}: {msg}")
                fallback_warnings.append(f"{name.capitalize()} unavailable ({msg})")
                continue
            except ProviderUnsupportedError as e:
                msg = "unsupported file type"
                errors.append(e)
                error_msgs.append(f"- {name.capitalize()}: {msg}")
                fallback_warnings.append(f"{name.capitalize()} unavailable ({msg})")
                continue
            except ProviderNotFoundError as e:
                msg = "model not found"
                errors.append(e)
                error_msgs.append(f"- {name.capitalize()}: {msg}")
                fallback_warnings.append(f"{name.capitalize()} unavailable ({msg})")
                continue
            except ProviderQuotaError as e:
                self.cooldowns[name] = current_time + 300.0
                msg = "quota exhausted"
                errors.append(e)
                error_msgs.append(f"- {name.capitalize()}: {msg}")
                fallback_warnings.append(f"{name.capitalize()} unavailable ({msg})")
                continue
            except ProviderTransientError as e:
                self.cooldowns[name] = current_time + 60.0
                msg = "timeout or temporary error"
                errors.append(e)
                error_msgs.append(f"- {name.capitalize()}: {msg}")
                fallback_warnings.append(f"{name.capitalize()} unavailable ({msg})")
                continue
            except Exception as e:
                msg = "unavailable"
                errors.append(e)
                error_msgs.append(f"- {name.capitalize()}: {msg}")
                fallback_warnings.append(f"{name.capitalize()} unavailable ({msg})")
                continue

        # If we got here, all providers failed
        summary = "All configured providers are currently unavailable:\n" + "\n".join(error_msgs)
        raise ProviderAggregateError(summary, errors=errors)
