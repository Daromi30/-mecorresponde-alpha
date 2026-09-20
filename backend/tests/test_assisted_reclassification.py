import pytest
from pathlib import Path
import shutil
import subprocess
import tempfile

from sqlalchemy import select

from app.family_manifest import FAMILY_MANIFEST
from app.models import AuditEvent, Case
from app.reviews import HumanReview
from app.routers import admin_review_resolution as review_routes
from app.services_v2 import create_human_review


ADMIN = {"Authorization": "Bearer test-admin-token"}
ADMIN_STATIC = Path(__file__).parents[1] / "app" / "admin_static"


def _unsupported_case(client):
    created = client.post(
        "/api/cases",
        json={"message": "Mi comunidad de propietarios me reclama una derrama extraordinaria"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["family"] is None
    assert body["status"] == "HUMAN_REVIEW"
    review = next(item for item in body["human_reviews"] if item["reason"] == "UNSUPPORTED_CLASSIFICATION")
    return body["id"], review["id"]


def test_admin_exposes_only_registered_resolution_families_for_assisted_routing(client):
    assert client.get("/api/admin/review-routing/families").status_code == 401

    response = client.get("/api/admin/review-routing/families", headers=ADMIN)
    assert response.status_code == 200, response.text
    families = response.json()["families"]
    assert {item["code"] for item in families} == set(FAMILY_MANIFEST)
    assert all(item["vertical"] in {entry.vertical for entry in FAMILY_MANIFEST.values()} for item in families)
    assert all(item["title"] for item in families)


def test_unsupported_review_must_be_reclassified_instead_of_generically_completed(client):
    _, review_id = _unsupported_case(client)

    generic = client.post(
        f"/api/admin/reviews/{review_id}/complete",
        headers=ADMIN,
        json={"reviewer_decision": "Parece una garantía"},
    )
    assert generic.status_code == 409, generic.text

    structured = client.post(
        f"/api/admin/reviews/{review_id}/resolve-structured",
        headers=ADMIN,
        json={
            "reviewer_decision": "Intento de completar sin clasificar",
            "fact_updates": [
                {
                    "key": "purchase.test_fact",
                    "value": True,
                    "state": "confirmed",
                    "materiality": "context",
                }
            ],
        },
    )
    assert structured.status_code == 409, structured.text


def test_assisted_reclassification_routes_to_registered_family_without_manual_legal_result(client, db):
    case_id, review_id = _unsupported_case(client)

    invalid = client.post(
        f"/api/admin/reviews/{review_id}/reclassify",
        headers=ADMIN,
        json={
            "target_family": "NOT-A-FAMILY",
            "reviewer_decision": "No debe aceptarse una familia inventada",
        },
    )
    assert invalid.status_code == 422, invalid.text

    response = client.post(
        f"/api/admin/reviews/{review_id}/reclassify",
        headers=ADMIN,
        json={
            "target_family": "C01",
            "reviewer_decision": "El relato describe un posible producto defectuoso y debe entrar al intake C01 para comprobar sus hechos.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["family"] == "C01"
    assert body["vertical"] == "purchases"
    assert body["case_status"] == "INTAKE"
    assert body["title"] == FAMILY_MANIFEST["C01"].title
    assert body["next_question"]["done"] is False

    case = db.get(Case, case_id)
    review = db.get(HumanReview, review_id)
    assert case is not None and review is not None
    db.refresh(case)
    db.refresh(review)
    assert case.family == "C01"
    assert case.vertical == "purchases"
    assert case.status == "INTAKE"
    assert review.status == "COMPLETED"
    assert review.reviewer_decision

    event = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "HUMAN_REVIEW_RECLASSIFIED_INTAKE",
        )
        .order_by(AuditEvent.created_at.desc())
    ).first()
    assert event is not None
    assert event.payload_json["target_family"] == "C01"
    assert event.payload_json["target_vertical"] == "purchases"

    detail = client.get(f"/api/admin/cases/{case_id}", headers=ADMIN)
    assert detail.status_code == 200, detail.text
    current = detail.json()
    assert current["family"] == "C01"
    assert current["decisions"] == []
    assert current["facts"] == []

    repeated = client.post(
        f"/api/admin/reviews/{review_id}/reclassify",
        headers=ADMIN,
        json={"target_family": "C02", "reviewer_decision": "Segundo intento"},
    )
    assert repeated.status_code == 409



def test_assisted_reclassification_question_failure_rolls_back_review_and_case(client, db, monkeypatch):
    case_id, review_id = _unsupported_case(client)

    def fail_next_question(*_args, **_kwargs):
        raise RuntimeError("synthetic next-question failure")

    monkeypatch.setattr(review_routes, "get_next_question", fail_next_question)

    with pytest.raises(RuntimeError, match="synthetic next-question failure"):
        client.post(
            f"/api/admin/reviews/{review_id}/reclassify",
            headers=ADMIN,
            json={
                "target_family": "C01",
                "reviewer_decision": "Clasificación sintética que debe hacer rollback completo.",
            },
        )

    db.rollback()
    db.expire_all()
    case = db.get(Case, case_id)
    review = db.get(HumanReview, review_id)
    assert case is not None
    assert review is not None
    assert case.family is None
    assert case.status == "HUMAN_REVIEW"
    assert review.status == "OPEN"
    assert review.completed_at is None
    assert review.reviewer_decision is None
    assert db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "HUMAN_REVIEW_RECLASSIFIED_INTAKE",
        )
    ).all() == []

def test_reclassification_endpoint_rejects_non_routing_human_review(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Compré un televisor y la tienda me rechaza la garantía porque está defectuoso"},
    )
    assert created.status_code == 200
    case = db.get(Case, created.json()["id"])
    assert case is not None
    review = create_human_review(
        db,
        case,
        reason="TEST_MATERIAL_UNCERTAINTY",
        priority="HIGH",
        context={"test": True},
    )
    db.commit()

    response = client.post(
        f"/api/admin/reviews/{review.id}/reclassify",
        headers=ADMIN,
        json={
            "target_family": "C02",
            "reviewer_decision": "No se puede usar el endpoint de clasificación para una revisión material",
        },
    )
    assert response.status_code == 409, response.text


def test_backoffice_exposes_assisted_routing_without_legal_override_and_javascript_parses():
    script = (ADMIN_STATIC / "structured_review.js").read_text(encoding="utf-8")
    assert "/api/admin/review-routing/families" in script
    assert "/reclassify" in script
    assert "UNSUPPORTED_CLASSIFICATION" in script
    assert "no puede introducir un veredicto" in script
    assert "target_family" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script

    node = shutil.which("node")
    if not node:
        return
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
