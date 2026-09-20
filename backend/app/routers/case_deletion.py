from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..case_lifecycle import CaseDeletionStorageError, delete_case_and_data
from ..case_locking import lock_case_for_update
from ..db import get_db
from ..models import Case
from ..schemas_v2 import CaseDeleteRequest
from ..security import clear_case_access_cookie, require_case_access


router = APIRouter(
    prefix="/api/cases",
    tags=["case-deletion"],
    dependencies=[Depends(require_case_access)],
)


@router.delete("/{case_id}")
def delete_case(
    case_id: str,
    payload: CaseDeleteRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    case = lock_case_for_update(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        result = delete_case_and_data(db, case)
    except CaseDeletionStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="Case deletion could not safely remove stored documents; no database deletion was committed",
        ) from exc
    clear_case_access_cookie(response, case_id)
    return {
        "status": "deleted",
        "case_id": result.case_id,
        "documents_deleted": result.documents_deleted,
    }
