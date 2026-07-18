"""``tm-build`` and ``tm-build-parallel`` commands (task 8).

Moved from ``cli.py`` (Change 5 task 4.6). The command functions are defined
in :mod:`src.components.interfaces.tm_commands`; this module registers them
on the Typer ``app`` with the :func:`handle_pipeline_errors` decorator.
"""
from __future__ import annotations

from src.components.interfaces import cli as _cli
from src.components.interfaces.tm_commands import tm_build, tm_build_parallel
from src.utils.cli_errors import handle_pipeline_errors

_cli.app.command("tm-build")(handle_pipeline_errors(tm_build))
_cli.app.command("tm-build-parallel")(handle_pipeline_errors(tm_build_parallel))
