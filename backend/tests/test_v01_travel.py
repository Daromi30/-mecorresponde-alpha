from app.engine.common import FactValue
from app.engine.v01 import CURRENT_RULE_REVIEW_BEFORE, evaluate_v01


def fv(value):
    return FactValue(value=value, state="confirmed", user_confirmed=True)


def base_facts():
    return {
        "travel.flight_cancelled_by_operating_carrier": fv(True),
        "travel.cancellation_notified_date": fv("2026-09-18"),
        "travel.departure_airport_in_eu": fv(True),
        "travel.confirmed_reservation": fv(True),
        "travel.fare_status": fv("public_fare"),
        "travel.package_trip": fv(False),
        "travel.booking_scope": fv("single_flight"),
        "travel.passenger_choice": fv("refund"),
        "travel.documented_ticket_price": fv(189.90),
        "travel.refund_received": fv(False),
        "system.analysis_date": fv("2026-09-21"),
    }


def test_v01_calculates_only_documented_outstanding_ticket_refund():
    result = evaluate_v01(base_facts())

    assert result.viability == "HIGH"
    assert result.rule_result == "APPLIES"
    assert result.claimable_amount == 189.90
    assert result.economic_value == 189.90
    assert result.next_action == "PREPARE_V01_CANCELLATION_REFUND"
    assert result.calculation["article_8_refund_days"] == 7
    assert result.calculation["article_7_compensation_included"] is False


def test_v01_subtracts_verified_partial_refund():
    facts = base_facts()
    facts["travel.refund_received"] = fv(True)
    facts["travel.refund_received_amount"] = fv(50.0)

    result = evaluate_v01(facts)

    assert result.viability == "HIGH"
    assert result.claimable_amount == 139.90
    assert result.calculation["already_refunded"] == 50.0


def test_v01_does_not_mix_refund_with_article_7_compensation():
    result = evaluate_v01(base_facts())

    assert result.remedies == ["REFUND_CANCELLED_FLIGHT_TICKET"]
    assert "compensación adicional del artículo 7" in result.reasoning_summary


def test_v01_fails_closed_for_inbound_third_country_scope():
    facts = base_facts()
    facts["travel.departure_airport_in_eu"] = fv(False)

    result = evaluate_v01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_V01_INBOUND_SCOPE"


def test_v01_fails_closed_for_package_or_multi_segment_pricing():
    package = base_facts()
    package["travel.package_trip"] = fv(True)
    assert evaluate_v01(package).next_action == "HUMAN_REVIEW_V01_PACKAGE_TRAVEL"

    multi = base_facts()
    multi["travel.booking_scope"] = fv("multi_segment_or_round_trip")
    assert evaluate_v01(multi).next_action == "HUMAN_REVIEW_V01_MULTI_SEGMENT_REFUND"


def test_v01_respects_nonpublic_fare_exclusion_but_keeps_frequent_flyer_scope():
    excluded = base_facts()
    excluded["travel.fare_status"] = fv("nonpublic_free_or_reduced")
    result = evaluate_v01(excluded)
    assert result.viability == "OUT_OF_SCOPE"
    assert result.next_action == "EXPLAIN_V01_NONPUBLIC_FARE_EXCLUSION"

    frequent = base_facts()
    frequent["travel.fare_status"] = fv("frequent_flyer_program")
    assert evaluate_v01(frequent).viability == "HIGH"


def test_v01_rule_has_a_preemptive_reform_review_guard():
    facts = base_facts()
    facts["system.analysis_date"] = fv(CURRENT_RULE_REVIEW_BEFORE.isoformat())

    result = evaluate_v01(facts)

    assert result.viability == "PROFESSIONAL_REVIEW"
    assert result.next_action == "HUMAN_REVIEW_V01_LEGAL_TRANSITION"


def test_v01_api_prepares_refund_with_eurlex_provenance(client):
    created = client.post(
        "/api/cases",
        json={"message": "Ryanair me ha cancelado el vuelo y quiero el reembolso del billete"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["family"] == "V01"
    assert case["vertical"] == "travel"

    for key, fact in base_facts().items():
        if key == "system.analysis_date":
            continue
        response = client.post(
            f"/api/cases/{case['id']}/facts",
            json={
                "key": key,
                "value": fact.value,
                "state": "confirmed",
                "user_confirmed": True,
            },
        )
        assert response.status_code == 200, response.text

    diagnosis = client.post(f"/api/cases/{case['id']}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "HIGH"

    prepared = client.post(f"/api/cases/{case['id']}/prepare-claim")
    assert prepared.status_code == 200, prepared.text
    body = prepared.json()
    assert body["claim_type"] == "V01_CANCELLED_FLIGHT_TICKET_REFUND"
    assert body["amount"] == 189.90
    assert body["legal_basis"][0]["rule_id"] == "AIR_CANCELLATION_REFUND_CURRENT"
    assert body["legal_basis"][0]["article"] == "3, 5.1(a), 8.1(a)"
    assert body["legal_basis"][0]["official_url"].startswith("https://eur-lex.europa.eu/")
    assert "no cuantifica ni reclama" in body["text"]

    sources = client.get(f"/api/cases/{case['id']}/legal-sources")
    assert sources.status_code == 200, sources.text
    item = sources.json()["sources"][0]
    assert item["jurisdiction"] == "EU"
    assert item["official_url"].startswith("https://eur-lex.europa.eu/")
