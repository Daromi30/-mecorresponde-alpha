from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..admin_auth import require_admin
from ..case_handoff import build_case_handoff
from ..db import get_db
from ..models import Case


router = APIRouter(
    prefix="/api/admin",
    tags=["admin-handoff"],
    dependencies=[Depends(require_admin)],
)


@router.get("/cases/{case_id}/handoff")
def admin_case_handoff(case_id: str, db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return build_case_handoff(db, case)
