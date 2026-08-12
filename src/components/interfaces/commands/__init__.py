"""Per-command modules for the Iraqi Legal Translation Agent CLI.

Each module registers its command(s) on the Typer ``app`` defined in
:mod:`src.components.interfaces.cli` via ``app.command()``. Importing this
package triggers registration of every command.
"""
from src.components.interfaces.commands import (  # noqa: F401
    batch,
    doctor,
    excel,
    ingest,
    pdf,
    tm_add,
    tm_build,
    translate,
    ui,
    word,
)
