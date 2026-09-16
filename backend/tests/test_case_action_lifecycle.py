from sqlalchemy import func, select

from app.models import Action, AuditEvent, Case, Communication, Deadline


def create_complete_e04b(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    facts = {
        "electricity.supply_end_date": "2026-06-03",
        "electricity.addon.identity": "Protección Hogar",
        "electricity.addon.ever_contracted": True,
        "electricity.addon.contracted_with_supply": True,
        "electricity.addon.keep_requested": False,
    }
    for key, value in facts.items():
        response = client.post(
            f"/api/cases/{case_id}/facts",
            json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
        )
        assert response.status_code == 200
    charges = client.post(
        f"/api/cases/{case_id}/charges",
        json={"charges": [{
            "amount": 8.99,
            "service_period_start": "2026-06-04",
            "service_period_end": "2026-07-03",
            "evidence_verified": True,
        }]},
    )
    assert charges.status_code == 200
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200
    package = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert package.status_code == 200
    return case_id, package.json()["action_id"]


def test_submission_completes_send_action_and_creates_single_wait_step(client, db):
    case_id, send_action_id = create_complete_e04b(client)

    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": "2026-09-16", "channel": "web", "reference_number": "REF-1"},
    )
    assert submitted.status_code == 200

    db.expire_all()
    send_action = db.get(Action, send_action_id)
    case = db.get(Case, case_id)
    assert send_action.status == "COMPLETED"
    assert send_action.completed_at is not None
    assert case.status == "WAITING_RESPONSE"

    wait_action = db.get(Action, case.current_action_id)
    assert wait_action.type == "WAIT_FOR_RESPONSE"
    assert wait_action.status == "OPEN"
    assert wait_action.payload_json["submitted_on"] == "2026-09-16"
    assert wait_action.payload_json["reference_number"] == "REF-1"

    duplicate = client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": "2026-09-17", "channel": "email", "reference_number": "REF-2"},
    )
    assert duplicate.status_code == 409

    db.expire_all()
    assert db.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "CLAIM_SUBMITTED",
        )
    ) == 1
    assert db.scalar(
        select(func.count()).select_from(Communication).where(
            Communication.case_id == case_id,
            Communication.direction == "OUTBOUND",
        )
    ) == 1
    assert db.scalar(
        select(func.count()).select_from(Deadline).where(Deadline.case_id == case_id)
    ) == 1


def test_company_response_closes_wait_action_before_next_resolution_step(client, db):
    case_id, _ = create_complete_e04b(client)
    assert client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": "2026-09-16", "channel": "web"},
    ).status_code == 200

    db.expire_all()
    case = db.get(Case, case_id)
    wait_action_id = case.current_action_id

    response = client.post(
        f"/api/cases/{case_id}/responses",
        json={"text": "Denegamos la devolución porque el contrato de mantenimiento es independiente."},
    )
    assert response.status_code == 200

    db.expire_all()
    wait_action = db.get(Action, wait_action_id)
    case = db.get(Case, case_id)
    assert wait_action.status == "COMPLETED"
    assert wait_action.completed_at is not None
    assert case.current_action_id != wait_action_id


def test_verified_outcome_closes_execution_action_and_leaves_no_pending_step(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]

    pending = client.post(
        f"/api/cases/{case_id}/outcome",
        json={"result_type": "FAVORABLE", "amount_recovered": 20.0, "verified_by_user": False},
    )
    assert pending.status_code == 200
    db.expire_all()
    case = db.get(Case, case_id)
    execution_action_id = case.current_action_id
    execution_action = db.get(Action, execution_action_id)
    assert execution_action.type == "VERIFY_EXECUTION"
    assert execution_action.status == "OPEN"

    verified = client.post(
        f"/api/cases/{case_id}/outcome",
        json={"result_type": "FAVORABLE", "amount_recovered": 20.0, "verified_by_user": True},
    )
    assert verified.status_code == 200

    db.expire_all()
    case = db.get(Case, case_id)
    execution_action = db.get(Action, execution_action_id)
    assert case.status == "RESOLVED"
    assert case.current_action_id is None
    assert execution_action.status == "COMPLETED"
    assert execution_action.completed_at is not None
