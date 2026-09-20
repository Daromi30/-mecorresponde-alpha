from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..auth import require_current_user
from ..auth_models import User
from ..case_locking import lock_case_for_update
from ..config import settings
from ..db import get_db
from ..models import Case
from ..security import CaseAccess, clear_case_access_cookie, require_case_access
from ..services_v2 import audit

router = APIRouter(
    prefix="/api/cases",
    tags=["account-cases"],
    dependencies=[Depends(require_case_access)],
)


@router.post("/{case_id}/claim")
def claim_case(
    case_id: str,
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    if (
        settings.email_verification_enforced
        and settings.transactional_email_operational
        and user.email_verified_at is None
    ):
        raise HTTPException(status_code=403, detail="Verify your email before saving cases to this account")

    case = lock_case_for_update(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.user_id and case.user_id != user.id:
        raise HTTPException(status_code=409, detail="Case already belongs to another account")

    newly_claimed = case.user_id is None
    case.user_id = user.id
    anonymous_access = db.get(CaseAccess, case.id)
    if anonymous_access:
        db.delete(anonymous_access)
    if newly_claimed:
        audit(db, case.id, "CASE_CLAIMED_BY_ACCOUNT", {"user_id": user.id})
    db.commit()
    clear_case_access_cookie(response, case.id)
    return {"case_id": case.id, "owned": True, "newly_claimed": newly_claimed}
