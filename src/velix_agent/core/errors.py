"""Centralized error hierarchy for VelixAgent.

All application-specific exceptions inherit from VelixError, enabling
consistent top-level error handling without scattering bare except clauses.
"""


class VelixError(Exception):
    """Base exception for all VelixAgent errors."""

    def __init__(self, message: str = "An unexpected error occurred") -> None:
        self.message = message
        super().__init__(self.message)


class ConfigurationError(VelixError):
    """Raised when configuration is invalid or cannot be resolved."""

    def __init__(self, message: str = "Invalid configuration") -> None:
        super().__init__(message)


class CLIError(VelixError):
    """Raised when a CLI-level error occurs."""

    def __init__(self, message: str = "CLI error") -> None:
        super().__init__(message)
