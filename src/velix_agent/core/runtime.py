"""Application runtime for VelixAgent.

The Runtime is the single integration point that holds resolved
application state and shared resources.  The CLI and REPL receive
a Runtime rather than creating their own dependencies.

Phase 1 keeps Runtime intentionally minimal.  Future phases will
attach the model gateway, tool registry, planner, executor, memory
engine, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console

from velix_agent.core.agent import Agent
from velix_agent.core.config import VelixConfig
from velix_agent.core.logging import setup_logging
from velix_agent.core.session import Session


@dataclass(slots=True)
class Runtime:
    """Application-level runtime state."""

    config: VelixConfig
    console: Console = field(default_factory=Console)
    session: Session = field(default_factory=Session.create)
    agent: Agent = field(init=False)

    def __post_init__(self) -> None:
        from velix_agent.providers.factory import get_provider

        provider = get_provider(self.config)
        self.agent = Agent(self.session, provider)

    @property
    def debug(self) -> bool:
        """Convenience accessor for debug mode."""
        return self.config.debug

    @classmethod
    def create(
        cls,
        *,
        debug: bool | None = None,
        console: Console | None = None,
    ) -> Runtime:
        """Build a Runtime from environment / defaults with optional CLI overrides.

        Parameters
        ----------
        debug:
            If provided, overrides the ``VELIX_DEBUG`` env / default value.
        console:
            If provided, uses this Rich Console instead of creating one.
        """
        config = VelixConfig()

        # CLI-level overrides take highest precedence.
        if debug is not None:
            config = config.model_copy(update={"debug": debug})
            if debug:
                config = config.model_copy(update={"log_level": "DEBUG"})

        setup_logging(level=config.log_level, debug=config.debug)

        return cls(
            config=config,
            console=console or Console(),
        )
