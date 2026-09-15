from sqlalchemy import select

from app.models import AuditEvent, Case, Evidence, Fact
from app.reviews import HumanReview
from app.services_v2 import create_case, create_human_review


ADMIN = {"Authorization": "Bearer test-admin-token"}


def make_review(db, message="La factura de luz es incorrecta y me han cobrado de más"):
    case = create_case(db, message)
    review = create_human_review(
        db,
        case,
        reason="MATERIAL_FACT_REVIEW",
        priority="HIGH",
        context={"source": "test"},
    )
    db.commit()
    db.refresh(case)
    db.refresh(review)
    return case, review


def test_structured_review_records_human_fact_with_strong_traceability(client, db):
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
            "reviewer_decision": "La factura permite fijar el importe correcto.",
            "reanalyze": False,
            "fact_updates": [
                {
                    "key": "electricity.billing.correct_amount",
                    "value": 80.0,
                    "state": "confirmed",
                    "materiality": "critical",
                    "note": "Importe contrastado manualmente con la factura aportada.",
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "COMPLETED"
    assert body["case_status"] == "REANALYZING"
    assert len(body["fact_ids"]) == 1
    assert body["updated_diagnosis"] is None

    db.expire_all()
    newest = db.scalars(
        select(Fact)
        .where(Fact.case_id == case.id, Fact.key == "electricity.billing.correct_amount")
        .order_by(Fact.created_at.desc())
    ).first()
    assert newest is not None
    assert newest.created_by == "human"
    assert newest.state == "confirmed"
    assert newest.user_confirmed is False
    assert newest.supersedes_fact_id == previous.id
    evidence = db.scalar(select(Evidence).where(Evidence.fact_id == newest.id))
    assert evidence is not None
    assert evidence.source_type == "human"
    assert evidence.strength == "strong"
    assert db.get(HumanReview, review.id).status == "COMPLETED"
    assert db.scalar(
        select(AuditEvent).where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "HUMAN_REVIEW_STRUCTURED_RESOLUTION",
        )
    ) is not None


def test_structured_review_can_reanalyze_deterministically_from_human_facts(client, db):
    case, review = make_review(db)
    response = client.post(
        f"/api/admin/reviews/{review.id}/resolve-structured",
        headers=ADMIN,
        json={
            "reviewer_decision": "Importes y fecha contrastados en revisión humana.",
            "fact_updates": [
                {
                    "key": "electricity.billing.invoice_date",
                    "value": "2026-07-01",
                    "state": "confirmed",
                    "materiality": "critical",
                },
                {
                    "key": "electricity.billing.billed_amount",
                    "value": 120.0,
                    "state": "confirmed",
                    "materiality": "critical",
                },
                {
                    "key": "electricity.billing.correct_amount",
                    "value": 80.0,
                    "state": "confirmed",
                    "materiality": "critical",
                },
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["updated_diagnosis"] is not None
    assert body["updated_diagnosis"]["viability"] == "HIGH"
    assert body["updated_diagnosis"]["claimable_amount"] == 40.0
    assert body["decision_id"]
    assert body["action_id"]
    assert body["case_status"] == "DIAGNOSED"

    db.expire_all()
    stored_case = db.get(Case, case.id)
    assert stored_case is not None
    assert stored_case.current_decision_id == body["decision_id"]


def test_structured_review_rejects_reserved_fact_namespaces_and_legal_overrides(client, db):
    _, review = make_review(db)
    reserved = client.post(
        f"/api/admin/reviews/{review.id}/resolve-structured",
        headers=ADMIN,
        json={
            "reviewer_decision": "Intento inválido",
            "fact_updates": [
                {"key": "system.analysis_date", "value": "2030-01-01", "state": "confirmed"}
            ],
        },
    )
    assert reserved.status_code == 422

    legal_override = client.post(
        f"/api/admin/reviews/{review.id}/resolve-structured",
        headers=ADMIN,
        json={
            "reviewer_decision": "Intento inválido",
            "viability": "HIGH",
            "fact_updates": [
                {
                    "key": "electricity.billing.correct_amount",
                    "value": 80,
                    "legal_basis": "invented",
                }
            ],
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
            "reviewer_decision": "No autorizado",
            "fact_updates": [
                {"key": "electricity.billing.correct_amount", "value": 80}
            ],
        },
    )
    assert response.status_code == 401
