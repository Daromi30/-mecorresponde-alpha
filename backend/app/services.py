"""Compatibility facade for the active resolution service layer.

The project previously carried two service implementations in parallel. All
runtime and test code now uses services_v2; this module re-exports that single
implementation so legacy imports cannot diverge from production behavior.
"""

from .services_v2 import *  # noqa: F401,F403
