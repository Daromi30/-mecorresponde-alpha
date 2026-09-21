from app.engine.common import FactValue
from app.engine.v01 import CURRENT_RULE_REVIEW_BEFORE
from app.engine.v02 import evaluate_v02


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def base_facts():
    return {
        "travel.departure_delay_hours": fv(5.5),
        "travel.departure_airport_in_eu": fv(True),
        "travel.confirmed_reservation": fv(True),
        "travel.fare_status": fv("public_fare"),
        "travel.package_trip": fv(False),
        "travel.booking_scope": fv("single_flight"),
        "travel.delay_refund_requested": fv(True),
        "travel.passenger_took_delayed_flight": fv(False),
        "travel.documented_ticket_price": fv(210.0),
        "travel.refund_received": fv(False),
        "system.analysis_date": fv("2026-09-21"),
    }


def test_v02_calculates_unused_ticket_refund_after_five_hour_delay():
    result = evaluate_v02(base_facts())

    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.claimable_amount == 210.0
    assert result.next_action == "PREPARE_V02_FIVE_HOUR_DELAY_REFUND"
    assert result.calculation["article_8_refund_days"] == 7
    assert result.calculation["article_7_compensation_included"] is False


def test_v02_below_five_hours_does_not_create_refund_right():
    facts = base_facts()
    facts["travel.departure_delay_hours"] = fv(4.99)

    result = evaluate_v02(facts)

    assert result.viability == "OUT_OF_SCOPE"
    assert result.next_action == "EXPLAIN_V02_DELAY_BELOW_FIVE_HOURS"


def test_v02_does_not_auto_refund_a_flight_the_passenger_used():
    facts = base_facts()
    facts["travel.passenger_took_delayed_flight"] = fv(True)

    result = evaluate_v02(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_V02_FLOWN_SEGMENT"


def test_v02_fails_closed_for_package_and_multisegment_scope():
    package = base_facts()
    package["travel.package_trip"] = fv(True)
    assert evaluate_v02(package).next_action == "HUMAN_REVIEW_V02_PACKAGE_TRAVEL"

    multi = base_facts()
    multi["travel.booking_scope"] = fv("multi_segment_or_round_trip")
    assert evaluate_v02(multi).next_action == "HUMAN_REVIEW_V02_MULTI_SEGMENT_REFUND"


def test_v02_uses_same_preemptive_legal_transition_guard_as_v01():
    facts = base_facts()
    facts["system.analysis_date"] = fv(CURRENT_RULE_REVIEW_BEFORE.isoformat())

    result = evaluate_v02(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_V02_LEGAL_TRANSITION"


def test_v02_api_prepares_refund_with_eurlex_provenance(client):
    created = client.post(
        "/api/cases",
        json={"message": "Mi vuelo lleva más de cinco horas de retraso y quiero el reembolso del billete"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["family"] == "V02"
    assert case["vertical"] == "travel"

    for key, fact in base_facts().items():
        if key == "system.analysis_date":
            continue
        response = client.post(
            f"/api/cases/{case['id']}/facts",
            json={"key": key, "value": fact.value, "state": "confirmed", "user_confirmed": True},
        )
        assert response.status_code == 200, response.text

    diagnosis = client.post(f"/api/cases/{case['id']}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "HIGH"

    prepared = client.post(f"/api/cases/{case['id']}/prepare-claim")
    assert prepared.status_code == 200, prepared.text
    body = prepared.json()
    assert body["claim_type"] == "V02_FIVE_HOUR_DELAY_TICKET_REFUND"
    assert body["amount"] == 210.0
    assert body["legal_basis"][0]["rule_id"] == "AIR_FIVE_HOUR_DELAY_REFUND_CURRENT"
    assert body["legal_basis"][0]["article"] == "3, 6.1(iii), 8.1(a)"
    assert body["legal_basis"][0]["official_url"].startswith("https://eur-lex.europa.eu/")
    assert "no cuantifica ni reclama" in body["text"]
