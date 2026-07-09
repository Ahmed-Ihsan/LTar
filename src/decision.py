"""Backward-compat shim — content moved to src.components.translation_pipeline.decision.

Temporary shim re-exporting ``route_tm`` so not-yet-migrated modules using
``from src.decision import ...`` keep working during the component-by-component
migration. Removed once all imports point to the new component paths.
"""
from src.components.translation_pipeline.decision import *  # noqa: F401,F403
