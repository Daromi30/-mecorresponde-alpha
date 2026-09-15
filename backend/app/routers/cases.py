"""Compatibility facade for the active case router.

The canonical API implementation lives in cases_v2. Keeping this import shim
prevents old imports from creating a second behavior path.
"""

from .cases_v2 import router

__all__ = ["router"]
