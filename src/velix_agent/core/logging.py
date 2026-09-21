"""Logging configuration for VelixAgent.

Wraps Python's standard ``logging`` module.  Debug mode enables verbose
output; normal mode stays clean.  Never logs secrets, API keys, or
environment dumps.
"""

from __future__ import annotations

import logging
import sys

_LOGGER_NAME = "velix_agent"
_CONFIGURED = False


def setup_logging(*, level: str = "WARNING", debug: bool = False) -> logging.Logger:
    """Configure and return the application logger.

    Calling this function multiple times is safe — duplicate handlers are
    prevented by tracking initialisation state.

    Parameters
    ----------
    level:
        Standard Python log-level name (``DEBUG``, ``INFO``, etc.).
    debug:
        When *True*, overrides *level* to ``DEBUG`` and uses a more
        detailed format.
    """
    global _CONFIGURED

    logger = logging.getLogger(_LOGGER_NAME)

    if _CONFIGURED:
        return logger

    effective_level = "DEBUG" if debug else level.upper()
    logger.setLevel(effective_level)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(effective_level)

    if debug:
        fmt = "%(asctime)s [%(levelname)s] %(name)s.%(funcName)s: %(message)s"
    else:
        fmt = "%(levelname)s: %(message)s"

    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)
    logger.propagate = False

    _CONFIGURED = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the application namespace.

    Parameters
    ----------
    name:
        Optional sub-name.  ``get_logger("cli")`` → ``velix_agent.cli``.
    """
    base = _LOGGER_NAME
    return logging.getLogger(f"{base}.{name}" if name else base)


def reset_logging() -> None:
    """Reset logging state — intended for tests only."""
    global _CONFIGURED
    logger = logging.getLogger(_LOGGER_NAME)
    logger.handlers.clear()
    _CONFIGURED = False
