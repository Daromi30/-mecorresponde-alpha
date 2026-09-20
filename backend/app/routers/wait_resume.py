from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..evidence_context import atomic_workflow_transaction
from ..models import Case
from ..security import require_case_access
from ..wait_resume import resume_wait_action


router = APIRouter(
    prefix="/api/cases",
    tags=["cases"],
    dependencies=[Depends(require_case_access)],
)


@router.post("/{case_id}/resume-wait")
def resume_wait(case_id: str, db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")

    with atomic_workflow_transaction(db) as commit:
        try:
            result, decision, action = resume_wait_action(db, case)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        response = {
            **result.to_dict(),
            "decision_id": decision.id,
            "action_id": action.id,
            "case_status": case.status,
        }
        commit()
        return response
