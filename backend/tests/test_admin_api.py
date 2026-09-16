from app.models import AuditEvent, Case, Outcome
from app.reviews import HumanReview
from app.services_v2 import create_case, create_human_review


ADMIN = {"Authorization": "Bearer test-admin-token"}


def make_review(db):
    case = create_case(db, "La factura de luz es incorrecta y me han cobrado de más")
    review = create_human_review(
        db,
        case,
        reason="TEST_REVIEW_REQUIRED",
        priority="HIGH",
        context={"source": "test"},
    )
    db.commit()
    db.refresh(case)
    db.refresh(review)
    return case, review


def test_admin_requires_runtime_secret(client):
    response = client.get("/api/admin/health")
    assert response.status_code == 401

    response = client.get("/api/admin/health", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401

    response = client.get("/api/admin/health", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["surface"] == "backoffice"


def test_backoffice_lists_review_queue_and_case_detail(client, db):
    case, review = make_review(db)

    queue = client.get("/api/admin/reviews?status=OPEN", headers=ADMIN)
    assert queue.status_code == 200
    item = next(x for x in queue.json() if x["id"] == review.id)
    assert item["case_id"] == case.id
    assert item["priority"] == "HIGH"
    assert item["case"]["family"] == "E02-A"

    detail = client.get(f"/api/admin/cases/{case.id}", headers=ADMIN)
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == case.id
    assert body["status"] == "HUMAN_REVIEW"
    assert any(r["id"] == review.id for r in body["human_reviews"])
    assert any(event["event_type"] == "HUMAN_REVIEW_TRIGGERED" for event in body["audit"])


def test_admin_can_assign_but_generic_free_text_cannot_complete_review(client, db):
    case, review = make_review(db)

    assigned = client.post(
        f"/api/admin/reviews/{review.id}/assign",
        headers=ADMIN,
        json={"assigned_to": "beta-reviewer"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_to"] == "beta-reviewer"

    blocked = client.post(
        f"/api/admin/reviews/{review.id}/complete",
        headers=ADMIN,
        json={"reviewer_decision": "Revisado: solicitar evidencia adicional antes de concluir."},
    )
    assert blocked.status_code == 409
    assert "generic note" in blocked.json()["detail"]

    db.expire_all()
    stored_review = db.get(HumanReview, review.id)
    stored_case = db.get(Case, case.id)
    assert stored_review is not None
    assert stored_review.status == "OPEN"
    assert stored_review.reviewer_decision is None
    assert stored_review.completed_at is None
    assert stored_case is not None
    assert stored_case.status == "HUMAN_REVIEW"


def test_admin_stats_are_aggregate_only(client, db):
    make_review(db)
    response = client.get("/api/admin/stats", headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["total_cases"] >= 1
    assert body["open_reviews"] >= 1
    assert "E02-A" in body["cases_by_family"]
    assert "electricity" in body["cases_by_vertical"]
    assert set(body["funnel"]) == {
        "started",
        "diagnosed",
        "action_prepared",
        "submitted",
        "response_analyzed",
        "resolved_verified",
    }


def test_admin_stats_measure_audited_funnel_and_verified_recovery(client, db):
    case = create_case(db, "La factura de luz es incorrecta y me han cobrado de más")
    for event_type in (
        "DIAGNOSIS_GENERATED",
        "CLAIM_PACKAGE_PREPARED",
        "CLAIM_SUBMITTED",
        "RESPONSE_ANALYZED",
    ):
        db.add(AuditEvent(case_id=case.id, event_type=event_type, payload_json={}))
    db.add(
        Outcome(
            case_id=case.id,
            result_type="REFUND",
            amount_recovered=42.50,
            verified_by_user=True,
        )
    )
    db.commit()

    response = client.get("/api/admin/stats", headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["funnel"]["started"] >= 1
    assert body["funnel"]["diagnosed"] >= 1
    assert body["funnel"]["action_prepared"] >= 1
    assert body["funnel"]["submitted"] >= 1
    assert body["funnel"]["response_analyzed"] >= 1
    assert body["funnel"]["resolved_verified"] >= 1
    assert body["verified_resolutions"] >= 1
    assert body["total_recovered"] >= 42.50


def test_backoffice_shell_loads_without_embedding_or_persisting_secret(client):
    response = client.get("/backoffice/")
    assert response.status_code == 200
    assert "Backoffice Beta" in response.text
    assert "Embudo del Motor" in response.text
    assert "test-admin-token" not in response.text
    assert "sessionStorage" not in response.text
    assert "localStorage" not in response.text
