"""Single DI entry point for the Iraqi Legal Translation Agent.

Re-exports the Typer ``app`` from the interfaces component and provides a
``main()`` callable used by the ``iraqi-translate`` console script
(``[project.scripts]`` in ``pyproject.toml``).

Usage::

    python -m src.app
    iraqi-translate doctor
"""
from src.components.interfaces.cli import app as _app


def main() -> None:
    """Console-script entry point — delegates to the Typer app."""
    _app()


if __name__ == "__main__":
    main()
