from sqlalchemy import func, select

from app.models import Case, Document


def _terminal_case(client, db, status: str) -> str:
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    case = db.get(Case, case_id)
    assert case is not None
    case.status = status
    db.commit()
    return case_id


def _document_count(db, case_id: str) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(Document).where(Document.case_id == case_id)
        )
        or 0
    )


def test_terminal_cases_reject_new_document_uploads_without_mutation(client, db):
    for status in ("RESOLVED", "CLOSED_UNSUPPORTED"):
        case_id = _terminal_case(client, db, status)
        before = _document_count(db, case_id)

        attempted = client.post(
            f"/api/cases/{case_id}/documents",
            files={"file": ("late-evidence.txt", b"late evidence", "text/plain")},
        )

        assert attempted.status_code == 409, attempted.text
        assert attempted.json()["detail"] == "Closed cases cannot accept new document uploads"
        db.expire_all()
        case = db.get(Case, case_id)
        assert case is not None
        assert case.status == status
        assert _document_count(db, case_id) == before
