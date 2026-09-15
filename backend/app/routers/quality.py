from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..case_quality import build_dossier_quality
from ..db import get_db
from ..models import Case, Decision, Evidence, Fact
from ..reviews import HumanReview
from ..security import require_case_access


router = APIRouter(
    prefix="/api/cases",
    tags=["case-quality"],
    dependencies=[Depends(require_case_access)],
)


@router.get("/{case_id}/quality")
def dossier_quality(case_id: str, db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    facts = db.scalars(
        select(Fact).where(Fact.case_id == case.id).order_by(Fact.created_at.asc())
    ).all()
    evidence = db.scalars(
        select(Evidence).where(Evidence.case_id == case.id).order_by(Evidence.created_at.asc())
    ).all()
    decisions = db.scalars(
        select(Decision).where(Decision.case_id == case.id).order_by(Decision.created_at.desc())
    ).all()
    reviews = db.scalars(
        select(HumanReview)
        .where(HumanReview.case_id == case.id)
        .order_by(HumanReview.created_at.desc())
    ).all()

    return build_dossier_quality(case, facts, evidence, decisions, reviews)
