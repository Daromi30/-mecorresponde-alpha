import pytest
from sqlalchemy import func, select

from app.models import AuditEvent, Case
from app.reviews import HumanReview
from app.security import CaseAccess


def _count(db, model) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_supported_anonymous_case_creation_uses_one_real_commit_for_case_and_access(client, db, monkeypatch):
    real_commit = db.commit
    commits = []

    def counted_commit():
        commits.append("commit")
        return real_commit()

    monkeypatch.setattr(db, "commit", counted_commit)
    response = client.post(
        "/api/cases",
        json={"message": "Me han cambiado de compañía de luz sin mi consentimiento"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(commits) == 1

    db.expire_all()
    case = db.get(Case, body["id"])
    access = db.get(CaseAccess, body["id"])
    assert case is not None
    assert access is not None
    assert access.token_hash
    assert db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.case_id == body["id"],
            AuditEvent.event_type == "CASE_ACCESS_ISSUED",
        )
    ) is not None


def test_unsupported_assisted_case_and_access_are_committed_together(client, db, monkeypatch):
    real_commit = db.commit
    commits = []

    def counted_commit():
        commits.append("commit")
        return real_commit()

    monkeypatch.setattr(db, "commit", counted_commit)
    response = client.post(
        "/api/cases",
        json={"message": "Mi comunidad de propietarios me reclama una derrama extraordinaria"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "HUMAN_REVIEW"
    assert len(commits) == 1

    db.expire_all()
    assert db.get(Case, body["id"]) is not None
    assert db.get(CaseAccess, body["id"]) is not None
    review = db.scalar(
        select(HumanReview).where(
            HumanReview.case_id == body["id"],
            HumanReview.reason == "UNSUPPORTED_CLASSIFICATION",
        )
    )
    assert review is not None and review.status == "OPEN"


def test_failed_outer_case_creation_commit_does_not_leave_an_inaccessible_orphan(client, db, monkeypatch):
    cases_before = _count(db, Case)
    access_before = _count(db, CaseAccess)

    def fail_final_commit():
        raise RuntimeError("forced outer commit failure")

    monkeypatch.setattr(db, "commit", fail_final_commit)
    with pytest.raises(RuntimeError, match="forced outer commit failure"):
        client.post(
            "/api/cases",
            json={"message": "Me han cambiado de compañía de luz sin mi consentimiento"},
        )

    db.rollback()
    assert _count(db, Case) == cases_before
    assert _count(db, CaseAccess) == access_before
