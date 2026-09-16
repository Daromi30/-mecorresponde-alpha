from sqlalchemy import func, select

from app.models import AuditEvent, Communication, Outcome


def create_submitted_case(client, submitted_on="2026-09-10"):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    for key, value in {
        "electricity.supply_end_date": "2026-06-03",
        "electricity.addon.identity": "Protección Hogar",
        "electricity.addon.ever_contracted": True,
        "electricity.addon.contracted_with_supply": True,
        "electricity.addon.keep_requested": False,
    }.items():
        assert client.post(
            f"/api/cases/{case_id}/facts",
            json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
        ).status_code == 200
    assert client.post(
        f"/api/cases/{case_id}/charges",
        json={"charges": [{
            "amount": 8.99,
            "service_period_start": "2026-06-04",
            "service_period_end": "2026-07-03",
            "evidence_verified": True,
        }]},
    ).status_code == 200
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 200
    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": submitted_on, "channel": "web_form", "reference_number": "CLAIM-1"},
    )
    assert submitted.status_code == 200
    return case_id


def accept_case(client, *, submitted_on="2026-09-10", received_on="2026-09-12"):
    case_id = create_submitted_case(client, submitted_on=submitted_on)
    accepted = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos su reclamación y procederemos a devolver el importe.",
            "received_on": received_on,
            "channel": "email",
            "reference_number": "RESPONSE-1",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["analysis"]["type"] == "ACCEPTANCE"
    assert accepted.json()["case_status"] == "RESOLVED_PENDING_EXECUTION"
    return case_id


def test_company_response_requires_a_real_submitted_waiting_phase(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    case_id = created.json()["id"]
    blocked = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={"text": "Aceptamos la reclamación.", "channel": "email"},
    )
    assert blocked.status_code == 409
    assert db.scalar(
        select(func.count()).select_from(Communication).where(Communication.case_id == case_id)
    ) == 0


def test_response_date_cannot_predate_submission(client, db):
    case_id = create_submitted_case(client, submitted_on="2026-09-10")
    blocked = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Denegamos la devolución.",
            "received_on": "2026-09-09",
            "channel": "email",
        },
    )
    assert blocked.status_code == 422
    assert db.scalar(
        select(func.count()).select_from(Communication).where(
            Communication.case_id == case_id,
            Communication.direction == "INBOUND",
        )
    ) == 0


def test_outcome_requires_favorable_response_pending_execution(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    case_id = created.json()["id"]
    blocked = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 25,
            "verified_by_user": True,
            "resolution_channel": "bank_or_card_refund",
        },
    )
    assert blocked.status_code == 409
    assert db.scalar(select(Outcome).where(Outcome.case_id == case_id)) is None


def test_verified_outcome_requires_execution_evidence_and_valid_chronology(client, db):
    case_id = accept_case(client, submitted_on="2026-09-10", received_on="2026-09-12")

    missing_evidence = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 0,
            "verified_by_user": True,
            "resolved_on": "2026-09-13",
        },
    )
    assert missing_evidence.status_code == 422

    bad_date = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 25,
            "verified_by_user": True,
            "resolved_on": "2026-09-11",
            "resolution_channel": "bank_or_card_refund",
        },
    )
    assert bad_date.status_code == 422

    valid = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 25,
            "verified_by_user": True,
            "resolved_on": "2026-09-13",
            "resolution_channel": "bank_or_card_refund",
        },
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["case_status"] == "RESOLVED"
    evidence = db.scalar(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "OUTCOME_EVIDENCE_RECORDED",
        )
    )
    assert evidence is not None
    assert evidence.payload_json["resolved_on"] == "2026-09-13"


def test_legacy_untraced_response_and_outcome_http_routes_fail_closed(client):
    case_id = create_submitted_case(client)
    legacy_response = client.post(
        f"/api/cases/{case_id}/responses",
        json={"text": "Aceptamos la reclamación."},
    )
    assert legacy_response.status_code == 409
    assert "evidenced" in legacy_response.json()["detail"]

    legacy_outcome = client.post(
        f"/api/cases/{case_id}/outcome",
        json={"result_type": "FAVORABLE", "verified_by_user": True},
    )
    assert legacy_outcome.status_code == 409
    assert "evidenced" in legacy_outcome.json()["detail"]
