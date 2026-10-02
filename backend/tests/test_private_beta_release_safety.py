"""Synthetic-only tests: the production private-beta interlock remains false."""

import pytest
from sqlalchemy import select

from app.auth_models import Reviewer
from app.backoffice_auth import create_reviewer
from app.config import settings
from app.models import Action, Case, Decision
from app.private_beta_release import RELEASE_REASON, ensure_release_review
from app.reviews import HumanReview
from app import real_beta_gate as gate


CASES = {
    "E02-A": (
        "La factura de luz es incorrecta y me han cobrado de más",
        [
            ("electricity.billing.invoice_date", "2026-09-01"),
            ("electricity.billing.billed_amount", 120),
            ("electricity.billing.correct_amount", 80),
        ],
    ),
    "C01": (
        "Compré un televisor defectuoso y no me respetan la garantía",
        [
            ("purchase.buyer_is_consumer", True),
            ("purchase.seller_is_business", True),
            ("purchase.second_hand", False),
            ("purchase.product_name", "televisor ficticio"),
            ("purchase.delivery_date", "2026-08-01"),
            ("purchase.defect_manifested_date", "2026-09-01"),
            ("purchase.defect_description", "No enciende"),
            ("purchase.accidental_damage_or_misuse", False),
            ("purchase.price", 150),
        ],
    ),
}


@pytest.fixture
def future_test_gate(monkeypatch):
    monkeypatch.setattr(settings, "real_beta_enabled", "true")
    monkeypatch.setattr(settings, "real_beta_allowlist", "E02-A,C01")
    monkeypatch.setattr(gate, "technical_prerequisites_ready", lambda: True)
    assert gate.REAL_BETA_LAUNCH_REVIEW_COMPLETE is False


def _admit(client, db, family):
    reviewer = create_reviewer(db, "testoperator", "synthetic-operator-password", "operator")
    db.commit()
    login = client.post("/api/backoffice-auth/login", json={
        "login_id": "testoperator", "password": "synthetic-operator-password",
    })
    assert login.status_code == 200
    invite = client.post("/api/admin/real-beta/invitations", json={"expires_in_hours": 24})
    assert invite.status_code == 201
    client.historical_account(f"release-{family.lower()}@example.com", "synthetic-strong-password")
    accept = client.post("/api/real-beta/invitations/accept", json={"token": invite.json()["token"]})
    assert accept.status_code == 200
    message, facts = CASES[family]
    created = client.post("/api/real-beta/cases", json={
        "message": message, "age_18_plus_attested": True,
    })
    assert created.status_code == 201, created.text
    assert created.json()["family"] == family
    return created.json()["id"], reviewer, facts


@pytest.mark.parametrize("family", ["E02-A", "C01"])
def test_private_release_requires_assigned_reviewer_for_current_decision(
    client, db, future_test_gate, family,
):
    case_id, reviewer, facts = _admit(client, db, family)
    for key, value in facts:
        response = client.post(f"/api/cases/{case_id}/facts", json={
            "key": key, "value": value, "state": "confirmed", "user_confirmed": True,
        })
        assert response.status_code == 200, response.text
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["status"] == "PENDING_HUMAN_REVIEW"
    assert diagnosis.json()["action_id"] is None
    case = db.get(Case, case_id)
    review = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case_id, HumanReview.reason == RELEASE_REASON,
    ))
    assert review is not None and review.status == "OPEN"
    assert case.status == "HUMAN_REVIEW"
    decision = db.get(Decision, case.current_decision_id)
    action = db.get(Action, case.current_action_id)
    ensure_release_review(db, case, decision, action)
    assert len(db.scalars(select(HumanReview).where(
        HumanReview.case_id == case_id, HumanReview.reason == RELEASE_REASON,
    )).all()) == 1

    detail = client.get(f"/api/cases/{case_id}")
    assert detail.status_code == 200
    assert detail.json()["actions"] == detail.json()["decisions"] == []
    exported = client.get("/api/auth/export")
    assert exported.status_code == 200
    exported_case = next(row for row in exported.json()["cases"] if row["id"] == case_id)
    assert exported_case["actions"] == exported_case["decisions"] == []
    assert client.get(f"/api/cases/{case_id}/handoff").status_code == 409
    internal_draft = client.get(f"/api/admin/cases/{case_id}/handoff")
    assert internal_draft.status_code == 200
    assert internal_draft.json()["latest_decision"] is not None
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 409
    assert client.post(f"/api/cases/{case_id}/submission", json={"submitted_on": "2026-09-01"}).status_code == 409
    assert client.post(f"/api/cases/{case_id}/reviews/{review.id}/complete", json={
        "reviewer_decision": "I approve myself",
    }).status_code == 403
    assert client.post(f"/api/admin/reviews/{review.id}/complete", json={
        "reviewer_decision": "generic note",
    }).status_code == 409

    assigned = client.post(f"/api/admin/reviews/{review.id}/assign", json={"reviewer_id": reviewer.id})
    assert assigned.status_code == 200, assigned.text
    assert client.post("/api/backoffice-auth/logout").status_code == 200
    assert client.post(f"/api/admin/reviews/{review.id}/approve-release").status_code == 401
    assert client.post("/api/backoffice-auth/login", json={
        "login_id": "testoperator", "password": "synthetic-operator-password",
    }).status_code == 200
    approved = client.post(f"/api/admin/reviews/{review.id}/approve-release")
    assert approved.status_code == 200, approved.text
    assert client.post(f"/api/admin/reviews/{review.id}/approve-release").status_code == 409
    released = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert released.status_code == 200, released.text
    assert client.get(f"/api/cases/{case_id}/handoff").status_code == 200


@pytest.mark.parametrize("family,wrong_key", [
    ("E02-A", "electricity.billing.unlisted"),
    ("C01", "purchase.unlisted"),
])
def test_private_fact_allowlist_rejects_unknown_fields(client, db, future_test_gate, family, wrong_key):
    case_id, _reviewer, _facts = _admit(client, db, family)
    response = client.post(f"/api/cases/{case_id}/facts", json={"key": wrong_key, "value": "secret"})
    assert response.status_code == 422
    assert client.post(f"/api/cases/{case_id}/facts", json={
        "key": next(iter(CASES[family][1]))[0], "value": {"unexpected": "shape"},
    }).status_code == 422


def test_adult_attestation_is_strict_and_does_not_open_the_production_interlock(client, db, future_test_gate):
    assert gate.REAL_BETA_LAUNCH_REVIEW_COMPLETE is False
    case_id, _reviewer, _facts = _admit(client, db, "E02-A")
    assert db.get(Case, case_id) is not None
    for value in (None, False, "true", 1):
        payload = {"message": CASES["E02-A"][0]}
        if value is not None:
            payload["age_18_plus_attested"] = value
        assert client.post("/api/real-beta/cases", json=payload).status_code == 422
    assert gate.REAL_BETA_LAUNCH_REVIEW_COMPLETE is False


def test_true_attestation_alone_never_opens_real_beta():
    assert gate.REAL_BETA_LAUNCH_REVIEW_COMPLETE is False
    assert gate.technical_prerequisites_ready() is False
    assert gate.real_beta_gate_open() is False
