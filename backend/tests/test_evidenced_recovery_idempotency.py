from sqlalchemy import func, select

from app.models import AIRun, Action, AuditEvent, Case, Communication, Outcome
from app.routers import cases_v2 as base_routes
from app.schemas_v2 import OutcomeInput, ResponseInput


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
        json={"charges": [{
            "amount": 8.99,
            "service_period_start": "2026-06-04",
            "service_period_end": "2026-07-03",
            "evidence_verified": True,
        }]},
    )
    assert charges.status_code == 200, charges.text
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 200
    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": "2026-09-10", "channel": "web_form", "reference_number": "CLAIM-1"},
    )
    assert submitted.status_code == 200, submitted.text
    return case_id


def _awaiting_execution(client) -> str:
    case_id = _submitted_e04b(client)
    response = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos su reclamación y procederemos a devolver el importe.",
            "received_on": "2026-09-12",
            "channel": "email",
            "reference_number": "RESP-OK",
        },
    )
    assert response.status_code == 200, response.text
    assert client.get(f"/api/cases/{case_id}").json()["status"] == "RESOLVED_PENDING_EXECUTION"
    return case_id


def _event_count(db, case_id: str, event_type: str) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.case_id == case_id,
                AuditEvent.event_type == event_type,
            )
        )
        or 0
    )


def test_response_evidence_retry_recovers_committed_analysis_without_replaying_workflow(client, db):
    case_id = _submitted_e04b(client)
    text = "Aceptamos su reclamación y procederemos a devolver el importe."

    # Simulate the historical failure window: the base workflow committed the response,
    # communication and state transition, but the evidenced route never attached metadata.
    stranded = base_routes.response(case_id, ResponseInput(text=text), db)
    assert stranded["analysis"]["type"] == "ACCEPTANCE"
    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None and case.status == "RESOLVED_PENDING_EXECUTION"
    assert _event_count(db, case_id, "COMPANY_RESPONSE_RECORDED") == 0
    inbound_before = db.scalars(
        select(Communication).where(
            Communication.case_id == case_id,
            Communication.direction == "INBOUND",
        )
    ).all()
    assert len(inbound_before) == 1
    analysis_runs_before = int(
        db.scalar(
            select(func.count()).select_from(AIRun).where(
                AIRun.case_id == case_id,
                AIRun.task == "analyze_response",
            )
        )
        or 0
    )
    verify_actions_before = int(
        db.scalar(
            select(func.count()).select_from(Action).where(
                Action.case_id == case_id,
                Action.type == "VERIFY_EXECUTION",
            )
        )
        or 0
    )

    recovered = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": text,
            "received_on": "2026-09-12",
            "channel": "email",
            "reference_number": "RESP-RECOVERED",
        },
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["analysis"]["type"] == "ACCEPTANCE"

    db.expire_all()
    inbound_after = db.scalars(
        select(Communication).where(
            Communication.case_id == case_id,
            Communication.direction == "INBOUND",
        )
    ).all()
    assert len(inbound_after) == 1
    assert inbound_after[0].channel == "email"
    assert inbound_after[0].reference_number == "RESP-RECOVERED"
    assert inbound_after[0].occurred_on.isoformat() == "2026-09-12"
    assert _event_count(db, case_id, "COMPANY_RESPONSE_RECORDED") == 1
    assert int(db.scalar(select(func.count()).select_from(AIRun).where(
        AIRun.case_id == case_id, AIRun.task == "analyze_response"
    )) or 0) == analysis_runs_before
    assert int(db.scalar(select(func.count()).select_from(Action).where(
        Action.case_id == case_id, Action.type == "VERIFY_EXECUTION"
    )) or 0) == verify_actions_before

    duplicate = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={"text": text, "received_on": "2026-09-12", "channel": "email"},
    )
    assert duplicate.status_code == 409
    assert _event_count(db, case_id, "COMPANY_RESPONSE_RECORDED") == 1


def test_outcome_evidence_retry_preserves_original_resolution_timestamp_and_does_not_reverify(client, db):
    case_id = _awaiting_execution(client)

    # Simulate the same window for execution verification: base outcome committed RESOLVED,
    # but resolved_on/channel/detail and OUTCOME_EVIDENCE_RECORDED were not written.
    stranded = base_routes.outcome(
        case_id,
        OutcomeInput(result_type="FAVORABLE", amount_recovered=35.5, verified_by_user=True),
        db,
    )
    assert stranded["case_status"] == "RESOLVED"
    db.expire_all()
    outcome_before = db.scalar(select(Outcome).where(Outcome.case_id == case_id))
    assert outcome_before is not None and outcome_before.resolved_at is not None
    original_resolved_at = outcome_before.resolved_at
    assert outcome_before.resolved_on is None
    assert _event_count(db, case_id, "OUTCOME_EVIDENCE_RECORDED") == 0
    outcome_recorded_before = _event_count(db, case_id, "OUTCOME_RECORDED")
    action_count_before = int(
        db.scalar(select(func.count()).select_from(Action).where(Action.case_id == case_id)) or 0
    )

    mismatch = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 99,
            "verified_by_user": True,
            "resolved_on": "2026-09-15",
            "resolution_channel": "bank_or_card_refund",
        },
    )
    assert mismatch.status_code == 409
    assert _event_count(db, case_id, "OUTCOME_EVIDENCE_RECORDED") == 0

    recovered = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 35.5,
            "verified_by_user": True,
            "resolved_on": "2026-09-15",
            "resolution_channel": "bank_or_card_refund",
            "non_monetary_result": None,
        },
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["case_status"] == "RESOLVED"
    assert recovered.json()["resolved_on"] == "2026-09-15"

    db.expire_all()
    outcome_after = db.scalar(select(Outcome).where(Outcome.case_id == case_id))
    assert outcome_after is not None
    assert outcome_after.resolved_at == original_resolved_at
    assert outcome_after.resolved_on.isoformat() == "2026-09-15"
    assert outcome_after.resolution_channel == "bank_or_card_refund"
    assert _event_count(db, case_id, "OUTCOME_RECORDED") == outcome_recorded_before
    assert _event_count(db, case_id, "OUTCOME_EVIDENCE_RECORDED") == 1
    assert int(db.scalar(select(func.count()).select_from(Action).where(Action.case_id == case_id)) or 0) == action_count_before

    duplicate = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 35.5,
            "verified_by_user": True,
            "resolved_on": "2026-09-15",
            "resolution_channel": "bank_or_card_refund",
        },
    )
    assert duplicate.status_code == 409
    assert _event_count(db, case_id, "OUTCOME_EVIDENCE_RECORDED") == 1
