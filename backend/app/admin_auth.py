from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db


def require_admin(
    request: Request,
    db: Session = Depends(get_db),
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

    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        from .models import Case
        from .real_beta_gate import require_real_case_mutation
        from .reviews import HumanReview

        case_id = request.path_params.get("case_id")
        review_id = request.path_params.get("review_id")
        if review_id:
            review = db.get(HumanReview, review_id)
            case_id = review.case_id if review else None
        if case_id:
            case = db.get(Case, case_id)
            if case is not None:
                require_real_case_mutation(db, case)
