"""Backward-compat shim — content moved to src.components.translation_pipeline.models.

This temporary shim re-exports the state schema so that not-yet-migrated
modules using ``from src.state import ...`` keep working during the
component-by-component migration. It is removed once all imports point to
the new component paths.
"""
from src.components.translation_pipeline.models import *  # noqa: F401,F403
