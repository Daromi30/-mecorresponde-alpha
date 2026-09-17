from sqlalchemy import func, select

from app.models import Action, AuditEvent, Case


def _fact(client, case_id: str, key: str, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _diagnosed_e04b(client) -> str:
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

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    current = client.get(f"/api/cases/{case_id}").json()
    assert current["status"] == "DIAGNOSED"
    assert current["current_decision_id"] == diagnosis.json()["decision_id"]
    return case_id


def test_prepare_claim_requires_current_diagnosis_after_claimant_fact_change(client, db):
    case_id = _diagnosed_e04b(client)

    first = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert first.status_code == 200, first.text
    first_action_id = first.json()["action_id"]

    repeated = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["action_id"] == first_action_id

    changed = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": "electricity.addon.identity",
            "value": "Protección Hogar Plus",
            "state": "confirmed",
            "user_confirmed": True,
        },
    )
    assert changed.status_code == 200, changed.text

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "INTAKE"
    assert case.current_decision_id is None
    assert case.current_action_id is None
    stale_action = db.get(Action, first_action_id)
    assert stale_action is not None
    assert stale_action.status == "SUPERSEDED"

    prepared_count_before = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "CLAIM_PACKAGE_PREPARED",
        )
    )

    blocked = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert blocked.status_code == 409, blocked.text
    assert "does not permit preparing" in blocked.json()["detail"].lower()

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.status == "INTAKE"
    assert case.current_decision_id is None
    assert case.current_action_id is None
    prepared_count_after_block = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "CLAIM_PACKAGE_PREPARED",
        )
    )
    assert int(prepared_count_after_block or 0) == int(prepared_count_before or 0)

    rediagnosed = client.post(f"/api/cases/{case_id}/diagnose")
    assert rediagnosed.status_code == 200, rediagnosed.text
    second = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert second.status_code == 200, second.text
    assert second.json()["action_id"] != first_action_id
