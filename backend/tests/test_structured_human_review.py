import pytest
from sqlalchemy import func, select

from app.models import Action, AuditEvent, Case, Decision, Evidence, Fact
from app.routers import admin_review_resolution as review_routes
from app.reviews import HumanReview
from app.services_v2 import create_case, create_human_review

ADMIN = {"Authorization": "Bearer test-admin-token"}


def make_review(db):
    case = create_case(db, "La factura de luz es incorrecta y me han cobrado de más")
    review = create_human_review(db, case, reason="MATERIAL_FACT_REVIEW", priority="HIGH")
    db.commit()
    db.refresh(case)
    db.refresh(review)
    return case, review


def test_structured_review_rejects_reanalysis_opt_out_without_mutation(client, db):
    case, review = make_review(db)
    before = db.scalar(select(func.count()).select_from(Fact).where(Fact.case_id == case.id))
    response = client.post(
        f"/api/admin/reviews/{review.id}/resolve-structured",
        headers=ADMIN,
        json={
            "reviewer_decision": "Dato revisado manualmente.",
            "reanalyze": False,
            "fact_updates": [{"key": "electricity.billing.correct_amount", "value": 80.0}],
        },
    )
    assert response.status_code == 422
    db.expire_all()
    assert db.get(HumanReview, review.id).status == "OPEN"
    assert db.get(Case, case.id).status == "HUMAN_REVIEW"
    after = db.scalar(select(func.count()).select_from(Fact).where(Fact.case_id == case.id))
    assert after == before


def test_structured_review_records_human_facts_then_reanalyzes(client, db):
    case, review = make_review(db)
    previous = Fact(
        case_id=case.id,
        key="electricity.billing.correct_amount",
        value_json={"value": 95.0},
        state="asserted",
        materiality="critical",
        user_confirmed=False,
        created_by="company",
    )
    db.add(previous)
    db.commit()
    db.refresh(previous)

    response = client.post(
        f"/api/admin/reviews/{review.id}/resolve-structured",
        headers=ADMIN,
        json={
            "reviewer_decision": "Importes y fecha contrastados en revisión humana.",
            "fact_updates": [
                {"key": "electricity.billing.invoice_date", "value": "2026-07-01", "materiality": "critical"},
                {"key": "electricity.billing.billed_amount", "value": 120.0, "materiality": "critical"},
                {
                    "key": "electricity.billing.correct_amount",
                    "value": 80.0,
                    "materiality": "critical",
                    "note": "Importe contrastado manualmente con la factura aportada.",
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_status"] == "COMPLETED"
    assert body["case_status"] == "DIAGNOSED"
    assert body["updated_diagnosis"]["viability"] == "HIGH"
    assert body["updated_diagnosis"]["claimable_amount"] == 40.0
    assert body["decision_id"] and body["action_id"]

    db.expire_all()
    newest = db.scalars(
        select(Fact)
        .where(Fact.case_id == case.id, Fact.key == "electricity.billing.correct_amount")
        .order_by(Fact.created_at.desc())
    ).first()
    assert newest.created_by == "human"
    assert newest.state == "confirmed"
    assert newest.user_confirmed is False
    assert newest.supersedes_fact_id == previous.id
    evidence = db.scalar(select(Evidence).where(Evidence.fact_id == newest.id))
    assert evidence is not None and evidence.source_type == "human" and evidence.strength == "strong"
    event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "HUMAN_REVIEW_STRUCTURED_RESOLUTION",
        )
    )
    assert event is not None
    assert event.payload_json["reanalyze_requested"] is True



def test_structured_review_failure_after_real_diagnosis_rolls_back_entire_resolution(client, db, monkeypatch):
    case, review = make_review(db)
    before = {
        "facts": int(db.scalar(select(func.count()).select_from(Fact).where(Fact.case_id == case.id)) or 0),
        "evidence": int(db.scalar(select(func.count()).select_from(Evidence).where(Evidence.case_id == case.id)) or 0),
        "decisions": int(db.scalar(select(func.count()).select_from(Decision).where(Decision.case_id == case.id)) or 0),
        "actions": int(db.scalar(select(func.count()).select_from(Action).where(Action.case_id == case.id)) or 0),
        "audits": int(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.case_id == case.id)) or 0),
    }

    real_diagnose = review_routes.diagnose

    def fail_after_real_diagnosis(db_session, case_row):
        real_diagnose(db_session, case_row)
        raise RuntimeError("synthetic post-diagnosis review failure")

    monkeypatch.setattr(review_routes, "diagnose", fail_after_real_diagnosis)

    with pytest.raises(RuntimeError, match="synthetic post-diagnosis review failure"):
        client.post(
            f"/api/admin/reviews/{review.id}/resolve-structured",
            headers=ADMIN,
            json={
                "reviewer_decision": "Importes contrastados antes del fallo sintético.",
                "fact_updates": [
                    {"key": "electricity.billing.invoice_date", "value": "2026-07-01"},
                    {"key": "electricity.billing.billed_amount", "value": 120.0},
                    {"key": "electricity.billing.correct_amount", "value": 80.0},
                ],
            },
        )

    db.rollback()
    db.expire_all()
    restored_review = db.get(HumanReview, review.id)
    restored_case = db.get(Case, case.id)
    assert restored_review is not None
    assert restored_review.status == "OPEN"
    assert restored_review.completed_at is None
    assert restored_review.reviewer_decision is None
    assert restored_case is not None
    assert restored_case.status == "HUMAN_REVIEW"
    assert int(db.scalar(select(func.count()).select_from(Fact).where(Fact.case_id == case.id)) or 0) == before["facts"]
    assert int(db.scalar(select(func.count()).select_from(Evidence).where(Evidence.case_id == case.id)) or 0) == before["evidence"]
    assert int(db.scalar(select(func.count()).select_from(Decision).where(Decision.case_id == case.id)) or 0) == before["decisions"]
    assert int(db.scalar(select(func.count()).select_from(Action).where(Action.case_id == case.id)) or 0) == before["actions"]
    assert int(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.case_id == case.id)) or 0) == before["audits"]

def test_structured_review_rejects_reserved_or_manual_legal_fields(client, db):
    _, review = make_review(db)
    reserved = client.post(
        f"/api/admin/reviews/{review.id}/resolve-structured",
        headers=ADMIN,
        json={
            "reviewer_decision": "Revisión de dato.",
            "fact_updates": [{"key": "system.analysis_date", "value": "2030-01-01"}],
        },
    )
    assert reserved.status_code == 422

    legal_override = client.post(
        f"/api/admin/reviews/{review.id}/resolve-structured",
        headers=ADMIN,
        json={
            "reviewer_decision": "Revisión de dato.",
            "viability": "HIGH",
            "fact_updates": [{"key": "electricity.billing.correct_amount", "value": 80}],
        },
    )
    assert legal_override.status_code == 422
    db.expire_all()
    assert db.get(HumanReview, review.id).status == "OPEN"


def test_structured_review_requires_admin_secret(client, db):
    _, review = make_review(db)
    response = client.post(
        f"/api/admin/reviews/{review.id}/resolve-structured",
        json={
            "reviewer_decision": "Revisión de dato.",
            "fact_updates": [{"key": "electricity.billing.correct_amount", "value": 80}],
        },
    )
    assert response.status_code == 401
