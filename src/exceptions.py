"""Backward-compat shim — content moved to src.components.translation_pipeline.exceptions.

Temporary shim re-exporting the domain exception hierarchy so not-yet-migrated
modules using ``from src.exceptions import ...`` keep working during the
component-by-component migration. Removed once all imports point to the new
component paths.
"""
from src.components.translation_pipeline.exceptions import *  # noqa: F401,F403
