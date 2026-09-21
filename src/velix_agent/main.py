"""VelixAgent entry point.

This module exposes the Typer ``app`` at package level and provides
a ``main()`` function for direct ``python -m velix_agent`` invocation.
"""

from velix_agent.cli.app import app

__all__ = ["app"]


def main() -> None:
    """Run the VelixAgent CLI."""
    app()


if __name__ == "__main__":
    main()
