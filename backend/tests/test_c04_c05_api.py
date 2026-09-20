from datetime import timedelta

from app.calendar_clock import spain_today
from app.services_v2 import EVALUATORS


RECENT_C05_RECEIVED_DATE = (spain_today() - timedelta(days=7)).isoformat()


def post_fact(client, cid, key, value, state="confirmed", user_confirmed=True):
    response = client.post(
        f"/api/cases/{cid}/facts",
        json={
            "key": key,
            "value": value,
            "state": state,
            "user_confirmed": user_confirmed,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_resolution_registry_contains_purchase_families():
    assert "C04" in EVALUATORS
    assert "C05" in EVALUATORS


def test_classifier_routes_c04_non_delivery(client):
    response = client.post(
        "/api/cases",
        json={"message": "Compré un pedido online y no me ha llegado, sigue sin entregar"},
    )
    assert response.status_code == 200
    assert response.json()["vertical"] == "purchases"
    assert response.json()["family"] == "C04"


def test_classifier_routes_c05_withdrawal(client):
    response = client.post(
        "/api/cases",
        json={"message": "Compré un producto online y quiero devolver la compra dentro de los 14 días"},
    )
    assert response.status_code == 200
    assert response.json()["vertical"] == "purchases"
    assert response.json()["family"] == "C05"


def build_c04_termination_case(client):
    created = client.post(
        "/api/cases",
        json={"message": "Compré una cafetera online y no me ha llegado el pedido"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["family"] == "C04", body
    cid = body["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Cafetera",
        "purchase.order_date": "2026-07-01",
        "purchase.amount_paid": 149.90,
        "purchase.delivered": False,
        "purchase.delivery_date_was_agreed": False,
        "purchase.seller_refused_delivery": False,
        "purchase.delivery_date_essential": False,
        "purchase.additional_delivery_period_requested": True,
        "purchase.additional_delivery_period_deadline": "2026-09-10",
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    current = client.get(f"/api/cases/{cid}")
    assert current.status_code == 200
    assert current.json()["family"] == "C04", current.json()
    return cid


def test_c04_end_to_end_termination_and_refund_claim(client):
    cid = build_c04_termination_case(client)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["claimable_amount"] == 149.90
    assert body["next_action"] == "PREPARE_NON_DELIVERY_TERMINATION"

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    payload = claim.json()
    assert payload["claim_type"] == "C04_NON_DELIVERY_TERMINATION"
    assert payload["amount"] == 149.90
    assert "66 bis" in payload["text"]


def test_c04_overdue_without_extra_period_builds_delivery_demand_not_refund(client):
    created_response = client.post(
        "/api/cases",
        json={"message": "Compré un pedido online y no lo he recibido"},
    )
    assert created_response.status_code == 200
    created = created_response.json()
    assert created["family"] == "C04", created
    cid = created["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Mesa",
        "purchase.order_date": "2026-07-01",
        "purchase.amount_paid": 300.0,
        "purchase.delivered": False,
        "purchase.delivery_date_was_agreed": False,
        "purchase.seller_refused_delivery": False,
        "purchase.delivery_date_essential": False,
        "purchase.additional_delivery_period_requested": False,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    diagnosis_response = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis_response.status_code == 200, diagnosis_response.text
    diagnosis = diagnosis_response.json()
    assert diagnosis["claimable_amount"] == 0.0
    assert diagnosis["next_action"] == "GIVE_ADDITIONAL_DELIVERY_PERIOD"
    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    assert claim.json()["claim_type"] == "C04_ADDITIONAL_DELIVERY_DEMAND"
    assert claim.json()["amount"] == 0.0


def build_c05_notice_case(client):
    created = client.post(
        "/api/cases",
        json={"message": "Compré unos auriculares online y quiero devolver la compra dentro de 14 días"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["family"] == "C05", body
    cid = body["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.distance_contract": True,
        "purchase.product_name": "Auriculares",
        "purchase.received_date": RECENT_C05_RECEIVED_DATE,
        "purchase.amount_paid": 120.0,
        "purchase.premium_delivery_extra": 0.0,
        "purchase.withdrawal_exception_possible": False,
        "purchase.withdrawal_information_provided": True,
        "purchase.withdrawal_sent": False,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    return cid


def test_c05_end_to_end_withdrawal_notice(client):
    cid = build_c05_notice_case(client)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["viability"] == "HIGH"
    assert body["next_action"] == "SEND_WITHDRAWAL_NOTICE"
    assert body["claimable_amount"] == 0.0

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    payload = claim.json()
    assert payload["claim_type"] == "C05_WITHDRAWAL_NOTICE"
    assert payload["amount"] == 0.0
    assert "102 a 108" in payload["text"]


def test_c05_overdue_refund_end_to_end(client):
    created_response = client.post(
        "/api/cases",
        json={"message": "Compré unos auriculares online, desistí y quiero la devolución"},
    )
    assert created_response.status_code == 200
    created = created_response.json()
    assert created["family"] == "C05", created
    cid = created["id"]
    facts = {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.distance_contract": True,
        "purchase.product_name": "Auriculares",
        "purchase.received_date": "2026-08-10",
        "purchase.amount_paid": 130.0,
        "purchase.premium_delivery_extra": 10.0,
        "purchase.withdrawal_exception_possible": False,
        "purchase.withdrawal_information_provided": True,
        "purchase.withdrawal_sent": True,
        "purchase.withdrawal_sent_date": "2026-08-20",
        "purchase.refund_received": False,
        "purchase.seller_offered_collection": False,
        "purchase.return_sent": True,
        "purchase.return_proof_available": True,
    }
    for key, value in facts.items():
        post_fact(client, cid, key, value)
    diagnosis = client.post(f"/api/cases/{cid}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    body = diagnosis.json()
    assert body["next_action"] == "PREPARE_WITHDRAWAL_REFUND_CLAIM"
    assert body["claimable_amount"] == 120.0

    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200, claim.text
    assert claim.json()["claim_type"] == "C05_WITHDRAWAL_REFUND"
    assert claim.json()["amount"] == 120.0
    assert "artículo 107" in claim.json()["text"]


def test_purchase_submission_still_does_not_invent_response_deadline(client):
    cid = build_c05_notice_case(client)
    client.post(f"/api/cases/{cid}/diagnose")
    client.post(f"/api/cases/{cid}/prepare-claim")
    response = client.post(
        f"/api/cases/{cid}/submission",
        json={"submitted_on": "2026-09-15"},
    )
    assert response.status_code == 200
    assert response.json()["deadline"] is None
    assert response.json()["deadline_status"] == "NOT_CONFIGURED"
