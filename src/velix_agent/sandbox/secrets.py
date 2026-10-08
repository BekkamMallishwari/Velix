"""Sandbox secret management and redaction.

Security Guarantee:
Secrets are explicitly injected into a sandbox execution environment, are not
inherited from the host by default, and are redacted from captured output. This
does not prevent a malicious process from deliberately transforming or exfiltrating
a secret. This is not an OS-level secure keychain or cryptographic wiping mechanism.
"""


class SecretStore:
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}
        self._registered_names: set[str] = set()

    def register(self, name: str, value: str) -> None:
        if not name or not value:
            raise ValueError("Secret name and value must not be empty.")
        if len(value) < 3:
            raise ValueError(
                f"Secret value for '{name}' is too short (min 3 characters) to safely redact."
            )
        self._secrets[name] = value
        self._registered_names.add(name)

    def create_environment(self, allowed_names: list[str]) -> dict[str, str]:
        env: dict[str, str] = {}
        for name in allowed_names:
            if name in self._secrets:
                env[name] = self._secrets[name]
        return env

    def redact(self, text: str) -> str:
        if not text:
            return text
        for _, value in self._secrets.items():
            text = text.replace(value, "***REDACTED***")
        return text

    def cleanup(self) -> None:
        self._secrets.clear()
        self._registered_names.clear()
