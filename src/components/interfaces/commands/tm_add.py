"""``tm-add-parallel`` command (task 8).

Moved from ``cli.py`` (Change 5 task 4.7). The command function is defined in
:mod:`src.components.interfaces.tm_commands`; this module registers it on the
Typer ``app`` with the :func:`handle_pipeline_errors` decorator.
"""
from __future__ import annotations

from src.components.interfaces import cli as _cli
from src.components.interfaces.tm_commands import tm_add_parallel
from src.utils.cli_errors import handle_pipeline_errors

_cli.app.command("tm-add-parallel")(handle_pipeline_errors(tm_add_parallel))
