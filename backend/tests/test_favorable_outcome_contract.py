from sqlalchemy import func, select

from app.models import Action, AuditEvent, Case, Outcome
from app.reviews import HumanReview


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
    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={
            "submitted_on": "2026-09-10",
            "channel": "web_form",
            "reference_number": "OUTCOME-CONTRACT-1",
        },
    )
    assert submitted.status_code == 200, submitted.text
    return case_id


def _awaiting_execution(client) -> str:
    case_id = _submitted_e04b(client)
    accepted = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos su reclamación y procederemos a devolver el importe.",
            "received_on": "2026-09-12",
            "channel": "email",
            "reference_number": "ACCEPTED-OUTCOME-CONTRACT",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["case_status"] == "RESOLVED_PENDING_EXECUTION"
    return case_id


def test_evidenced_outcome_rejects_incompatible_result_type_without_mutation(client, db):
    case_id = _awaiting_execution(client)

    response = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "DENIED",
            "amount_recovered": 8.99,
            "verified_by_user": True,
            "remaining_material_commitments": "none",
            "resolved_on": "2026-09-13",
            "resolution_channel": "bank_or_card_refund",
        },
    )
    assert response.status_code == 422, response.text

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "RESOLVED_PENDING_EXECUTION"
    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.type == "VERIFY_EXECUTION"
    assert current.status == "OPEN"
    assert db.scalar(select(Outcome).where(Outcome.case_id == case_id)) is None

    evidence_audits = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "OUTCOME_EVIDENCE_RECORDED",
        )
    )
    recorded_outcomes = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "OUTCOME_RECORDED",
        )
    )
    assert int(evidence_audits or 0) == 0
    assert int(recorded_outcomes or 0) == 0


def test_unknown_company_response_moves_to_protected_human_review_without_rewinding(client, db):
    case_id = _submitted_e04b(client)

    response = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Hemos recibido su escrito y lo estamos revisando internamente.",
            "received_on": "2026-09-12",
            "channel": "email",
            "reference_number": "UNKNOWN-RESPONSE-1",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis"]["type"] == "UNKNOWN"
    assert body["case_status"] == "HUMAN_REVIEW"

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "HUMAN_REVIEW"

    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.type == "HUMAN_REVIEW"
    assert current.status == "OPEN"
    assert (current.payload_json or {}).get("reason") == "UNRECOGNIZED_COMPANY_RESPONSE"

    review = db.scalars(
        select(HumanReview).where(
            HumanReview.case_id == case_id,
            HumanReview.status == "OPEN",
            HumanReview.reason == "UNRECOGNIZED_COMPANY_RESPONSE",
        )
    ).first()
    assert review is not None

    waiting_actions = db.scalars(
        select(Action).where(Action.case_id == case_id, Action.type == "WAIT_FOR_RESPONSE")
    ).all()
    assert waiting_actions
    assert all(action.status == "COMPLETED" for action in waiting_actions)

    ready_initial_actions = db.scalar(
        select(func.count())
        .select_from(Action)
        .where(
            Action.case_id == case_id,
            Action.type == "SUBMIT_INITIAL_CLAIM",
            Action.status == "READY",
        )
    )
    submitted_events = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "CLAIM_SUBMITTED",
        )
    )
    assert int(ready_initial_actions or 0) == 0
    assert int(submitted_events or 0) == 1
    assert db.scalar(select(Outcome).where(Outcome.case_id == case_id)) is None
