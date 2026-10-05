from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..case_handoff import build_case_handoff
from ..db import get_db
from ..models import Case
from ..private_beta_release import require_release_approval
from ..security import require_case_access


router = APIRouter(
    prefix="/api/cases",
    tags=["case-handoff"],
    dependencies=[Depends(require_case_access)],
)


@router.get("/{case_id}/handoff")
def case_handoff(case_id: str, db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    require_release_approval(db, case)
    return build_case_handoff(db, case)
