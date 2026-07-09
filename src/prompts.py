"""Backward-compat shim — content moved to src.components.translation_pipeline.prompts.

Temporary shim re-exporting the versioned prompt constants so not-yet-migrated
modules using ``from src.prompts import ...`` keep working during the
component-by-component migration. Removed once all imports point to the new
component paths.
"""
from src.components.translation_pipeline.prompts import *  # noqa: F401,F403
