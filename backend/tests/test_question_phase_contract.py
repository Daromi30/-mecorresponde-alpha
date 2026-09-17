from app.models import Case


LOCKED_STATUSES = (
    "HUMAN_REVIEW",
    "REANALYZING",
    "WAITING_RESPONSE",
    "RESPONSE_RECEIVED",
    "RESOLVED_PENDING_EXECUTION",
    "RESOLVED",
    "CLOSED_UNSUPPORTED",
)


def _new_incomplete_case(client) -> str:
    created = client.post(
        "/api/cases",
        json={"message": "Compré una cafetera online y no me ha llegado el pedido"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["family"] == "C04"
    return created.json()["id"]


def test_active_intake_still_exposes_the_real_guided_question(client):
    case_id = _new_incomplete_case(client)
    response = client.get(f"/api/cases/{case_id}/next-question")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["done"] is False
    assert body["field"] == "purchase.buyer_is_consumer"
    assert body["question"]


def test_diagnosed_phase_remains_available_for_registered_followups(client, db):
    case_id = _new_incomplete_case(client)
    case = db.get(Case, case_id)
    assert case is not None
    case.status = "DIAGNOSED"
    db.commit()

    response = client.get(f"/api/cases/{case_id}/next-question")
    assert response.status_code == 200, response.text
    assert response.json()["done"] is False
    assert response.json()["field"] == "purchase.buyer_is_consumer"


def test_protected_and_terminal_phases_never_expose_stale_claimant_questions(client, db):
    case_id = _new_incomplete_case(client)

    for status in LOCKED_STATUSES:
        case = db.get(Case, case_id)
        assert case is not None
        case.status = status
        db.commit()
        db.expire_all()

        response = client.get(f"/api/cases/{case_id}/next-question")
        assert response.status_code == 200, (status, response.text)
        body = response.json()
        assert body == {"done": True, "question": None, "field": None}, status
