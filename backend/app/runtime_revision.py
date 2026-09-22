import os
import re


UNKNOWN_RUNTIME_REVISION = "unknown"
_FULL_GIT_SHA = re.compile(r"[0-9a-fA-F]{40}")


def normalize_runtime_revision(value: str | None) -> str:
    """Return a trustworthy full Git SHA or an explicit unknown value."""
    if value is None or _FULL_GIT_SHA.fullmatch(value) is None:
        return UNKNOWN_RUNTIME_REVISION
    return value


def get_runtime_revision() -> str:
    return normalize_runtime_revision(os.getenv("RENDER_GIT_COMMIT"))
