from datetime import timedelta

from sqlalchemy import func, select

from app.calendar_clock import spain_today
from app.models import Action, AuditEvent, Case, Communication, Outcome


def _fact(client, case_id: str, key: str, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _submitted_e04b(client) -> str:
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]

    for key, value in {
        "electricity.supply_end_date": "2026-06-03",
        "electricity.addon.identity": "Protección Hogar",
        "electricity.addon.ever_contracted": True,
        "electricity.addon.contracted_with_supply": True,
        "electricity.addon.keep_requested": False,
    }.items():
        _fact(client, case_id, key, value)

    charges = client.post(
        f"/api/cases/{case_id}/charges",
        json={
            "charges": [
                {
                    "amount": 8.99,
                    "service_period_start": "2026-06-04",
                    "service_period_end": "2026-07-03",
                    "evidence_verified": True,
                }
            ]
        },
    )
    assert charges.status_code == 200, charges.text
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 200

    submitted_on = spain_today() - timedelta(days=2)
    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": submitted_on.isoformat(), "channel": "web_form"},
    )
    assert submitted.status_code == 200, submitted.text
    return case_id


def _awaiting_execution(client) -> str:
    case_id = _submitted_e04b(client)
    received_on = spain_today() - timedelta(days=1)
    accepted = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos su reclamación y procederemos a devolver el importe.",
            "received_on": received_on.isoformat(),
            "channel": "email",
            "reference_number": "ACCEPTED-1",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["case_status"] == "RESOLVED_PENDING_EXECUTION"
    return case_id


def test_future_company_response_date_is_rejected_without_mutating_case(client, db):
    case_id = _submitted_e04b(client)
    tomorrow = spain_today() + timedelta(days=1)

    response = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Denegamos la reclamación porque el contrato es independiente.",
            "received_on": tomorrow.isoformat(),
            "channel": "email",
            "reference_number": "FUTURE-RESPONSE",
        },
    )
    assert response.status_code == 422, response.text
    assert "future" in response.json()["detail"].lower()

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "WAITING_RESPONSE"
    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.type == "WAIT_FOR_RESPONSE"
    assert current.status == "OPEN"

    inbound_count = db.scalar(
        select(func.count())
        .select_from(Communication)
        .where(Communication.case_id == case_id, Communication.direction == "INBOUND")
    )
    evidence_audit_count = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "COMPANY_RESPONSE_RECORDED",
        )
    )
    assert int(inbound_count or 0) == 0
    assert int(evidence_audit_count or 0) == 0


def test_future_fulfillment_date_is_rejected_without_closing_case(client, db):
    case_id = _awaiting_execution(client)
    tomorrow = spain_today() + timedelta(days=1)

    response = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 8.99,
            "verified_by_user": True,
            "resolved_on": tomorrow.isoformat(),
            "resolution_channel": "bank_or_card_refund",
            "non_monetary_result": None,
        },
    )
    assert response.status_code == 422, response.text
    assert "future" in response.json()["detail"].lower()

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "RESOLVED_PENDING_EXECUTION"
    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.type == "VERIFY_EXECUTION"
    assert current.status == "OPEN"

    outcome = db.scalar(select(Outcome).where(Outcome.case_id == case_id))
    evidence_audit_count = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "OUTCOME_EVIDENCE_RECORDED",
        )
    )
    assert outcome is None
    assert int(evidence_audit_count or 0) == 0
