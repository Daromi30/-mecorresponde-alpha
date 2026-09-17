from sqlalchemy import select

from app.models import Action, AuditEvent, Case, Decision


def _fact(client, case_id: str, key: str, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _remote_failure_with_real_reading(client) -> str:
    created = client.post(
        "/api/cases",
        json={"message": "Mi factura de luz tiene una lectura estimada porque falló la lectura remota"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    assert created.json()["family"] == "E06"
    for key, value in {
        "electricity.reading_issue_invoice_date": "2026-09-01",
        "electricity.meter_fraud_tampering_or_complex_technical_issue": False,
        "electricity.reading_issue_type": "estimated_reading",
        "electricity.estimated_reading_reason": "remote_reading_failure",
        "electricity.real_reading_obtained_within_bimonthly_cycle": True,
    }.items():
        _fact(client, case_id, key, value)
    return case_id


def test_e06_bill_check_is_exposed_as_guided_external_followup(client, db):
    case_id = _remote_failure_with_real_reading(client)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "LOW"
    assert diagnosis.json()["next_action"] == "CHECK_BILL_AGAINST_REAL_READING"
    old_action_id = diagnosis.json()["action_id"]

    question = client.get(f"/api/cases/{case_id}/next-question")
    assert question.status_code == 200, question.text
    assert question.json() == {
        "done": False,
        "question": "Al comparar la factura con la lectura real, ¿el consumo facturado coincide con esa lectura?",
        "field": "electricity.bill_matches_real_reading",
        "input_type": "boolean",
    }

    answered = _fact(client, case_id, "electricity.bill_matches_real_reading", True)
    assert answered["next_question"]["done"] is True

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "INTAKE"
    assert case.current_action_id is None
    assert case.current_decision_id is None
    old_action = db.get(Action, old_action_id)
    assert old_action is not None
    assert old_action.status == "SUPERSEDED"


def test_e06_matching_bill_closes_check_without_new_claim(client, db):
    case_id = _remote_failure_with_real_reading(client)
    first = client.post(f"/api/cases/{case_id}/diagnose")
    assert first.status_code == 200, first.text
    assert first.json()["next_action"] == "CHECK_BILL_AGAINST_REAL_READING"

    _fact(client, case_id, "electricity.bill_matches_real_reading", True)
    rediagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert rediagnosis.status_code == 200, rediagnosis.text
    body = rediagnosis.json()
    assert body["viability"] == "LOW"
    assert body["scope_status"] == "SUPPORTED"
    assert body["next_action"] == "EXPLAIN_BILL_MATCHES_REAL_READING"
    assert body["claimable_amount"] == 0.0

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.family == "E06"
    assert case.status == "DIAGNOSED"
    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.type == "EXPLAIN_BILL_MATCHES_REAL_READING"
    events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "EXTERNAL_FOLLOWUP_ROUTED",
        )
    ).all()
    assert events
    assert events[-1].payload_json["route"] == "E06_CLOSED"


def test_e06_mismatching_bill_reclassifies_to_e02a_without_rewriting_source_decision(client, db):
    case_id = _remote_failure_with_real_reading(client)
    first = client.post(f"/api/cases/{case_id}/diagnose")
    assert first.status_code == 200, first.text
    assert first.json()["next_action"] == "CHECK_BILL_AGAINST_REAL_READING"

    _fact(client, case_id, "electricity.bill_matches_real_reading", False)
    rediagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert rediagnosis.status_code == 200, rediagnosis.text

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.family == "E02-A"
    assert case.vertical == "electricity"
    assert case.status == "NEEDS_INFORMATION"
    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.type == "REQUEST_MATERIAL_FACT"
    assert current.status == "OPEN"

    question = client.get(f"/api/cases/{case_id}/next-question")
    assert question.status_code == 200, question.text
    assert question.json()["field"] == "electricity.billing.invoice_date"

    events = db.scalars(
        select(AuditEvent).where(AuditEvent.case_id == case_id)
    ).all()
    event_types = [event.event_type for event in events]
    assert "EXTERNAL_FOLLOWUP_ROUTED" in event_types
    assert "CASE_RECLASSIFIED_BY_ENGINE" in event_types

    routed = [event for event in events if event.event_type == "EXTERNAL_FOLLOWUP_ROUTED"][-1]
    assert routed.payload_json["route"] == "E02-A"
    assert routed.payload_json["decision_viability"] == "LOW"

    source_decision = db.get(Decision, routed.payload_json["decision_id"])
    source_action = db.get(Action, routed.payload_json["action_id"])
    assert source_decision is not None
    assert source_decision.viability == "LOW"
    assert source_decision.scope_status == "SUPPORTED"
    assert source_action is not None
    assert source_action.type == "RECLASSIFY_E02_A"
    assert source_action.status == "COMPLETED"

    source_diagnosis_event = next(
        event
        for event in events
        if event.event_type == "DIAGNOSIS_GENERATED"
        and event.payload_json.get("decision_id") == source_decision.id
    )
    assert source_diagnosis_event.payload_json["viability"] == source_decision.viability
    assert source_diagnosis_event.payload_json["family"] == "E06"
