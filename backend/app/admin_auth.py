from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from .config import settings


def require_admin(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """Protect internal backoffice endpoints with a runtime-only secret.

    The token is supplied through deployment environment variables and never
    committed to the repository. Returning 401 for invalid credentials is fine
    here because the existence of the admin surface itself is not sensitive.
    """
    expected = settings.admin_api_token.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Backoffice is not configured")

    supplied = x_admin_token
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization[7:].strip()

    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid backoffice credentials")
