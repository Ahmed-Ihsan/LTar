"""Backward-compat shim — content moved to src.components.translation_pipeline.graph.

Temporary shim re-exporting ``build_graph`` and routing helpers so
not-yet-migrated modules using ``from src.graph import ...`` keep working
during the component-by-component migration. Removed once all imports point
to the new component paths.
"""
from src.components.translation_pipeline.graph import *  # noqa: F401,F403
