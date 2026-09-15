from app.models import Case
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


def test_admin_can_assign_and_complete_review(client, db):
    case, review = make_review(db)

    assigned = client.post(
        f"/api/admin/reviews/{review.id}/assign",
        headers=ADMIN,
        json={"assigned_to": "beta-reviewer"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_to"] == "beta-reviewer"

    completed = client.post(
        f"/api/admin/reviews/{review.id}/complete",
        headers=ADMIN,
        json={"reviewer_decision": "Revisado: solicitar evidencia adicional antes de concluir."},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert completed.json()["case_status"] == "REANALYZING"

    db.expire_all()
    assert db.get(HumanReview, review.id).status == "COMPLETED"
    assert db.get(Case, case.id).status == "REANALYZING"


def test_admin_stats_are_aggregate_only(client, db):
    make_review(db)
    response = client.get("/api/admin/stats", headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["total_cases"] >= 1
    assert body["open_reviews"] >= 1
    assert "E02-A" in body["cases_by_family"]


def test_backoffice_shell_loads_without_embedding_secret(client):
    response = client.get("/backoffice/")
    assert response.status_code == 200
    assert "Backoffice Beta" in response.text
    assert "test-admin-token" not in response.text
