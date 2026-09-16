from app.reviews import HumanReview


def create_case_with_human_review(client):
    created = client.post(
        "/api/cases",
        json={"message": "La factura de luz es incorrecta y me han cobrado de más"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    for key, value in {
        "electricity.billing.invoice_date": "2026-05-01",
        "electricity.billing.billed_amount": 150.0,
        "electricity.billing.correct_amount": 100.0,
    }.items():
        response = client.post(
            f"/api/cases/{case_id}/facts",
            json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
        )
        assert response.status_code == 200
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200
    assert diagnosis.json()["scope_status"] == "LEGACY_REVIEW"
    reviews = client.get(f"/api/cases/{case_id}/reviews")
    assert reviews.status_code == 200
    review_id = reviews.json()[0]["id"]
    return case_id, review_id


def assert_review_still_open(db, review_id):
    db.expire_all()
    review = db.get(HumanReview, review_id)
    assert review is not None
    assert review.status == "OPEN"
    assert review.reviewer_decision is None
    assert review.completed_at is None


def test_anonymous_case_holder_cannot_complete_human_review(client, db):
    case_id, review_id = create_case_with_human_review(client)

    blocked = client.post(
        f"/api/cases/{case_id}/reviews/{review_id}/complete",
        json={"reviewer_decision": "Me doy por revisado"},
    )

    assert blocked.status_code == 403
    assert "protected backoffice" in blocked.json()["detail"]
    assert_review_still_open(db, review_id)


def test_authenticated_case_owner_cannot_complete_own_human_review(client, db):
    case_id, review_id = create_case_with_human_review(client)
    registered = client.post(
        "/api/auth/register",
        json={
            "email": "review-gate-owner@example.com",
            "password": "correct-horse-battery-staple",
        },
    )
    assert registered.status_code == 201
    claimed = client.post(f"/api/cases/{case_id}/claim")
    assert claimed.status_code == 200

    blocked = client.post(
        f"/api/cases/{case_id}/reviews/{review_id}/complete",
        json={"reviewer_decision": "Intento cerrar mi propia revisión"},
    )

    assert blocked.status_code == 403
    assert "protected backoffice" in blocked.json()["detail"]
    assert_review_still_open(db, review_id)
