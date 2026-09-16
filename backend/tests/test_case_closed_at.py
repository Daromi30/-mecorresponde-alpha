from sqlalchemy import select

from app.models import Case, Outcome


def _awaiting_execution(client):
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
        response = client.post(
            f"/api/cases/{case_id}/facts",
            json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
        )
        assert response.status_code == 200, response.text
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
    assert client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": "2026-09-10", "channel": "web_form"},
    ).status_code == 200
    accepted = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos su reclamación y procederemos a devolver el importe.",
            "received_on": "2026-09-12",
            "channel": "email",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["case_status"] == "RESOLVED_PENDING_EXECUTION"
    return case_id


def test_persistence_policy_sets_closed_at_only_for_terminal_states(db):
    case = Case(status="INTAKE", vertical="electricity", family="E02-A", title="Closure invariant")
    db.add(case)
    db.commit()
    assert case.closed_at is None

    case.status = "RESOLVED_PENDING_EXECUTION"
    db.commit()
    assert case.closed_at is None

    case.status = "RESOLVED"
    db.commit()
    db.refresh(case)
    assert case.closed_at is not None

    first_closed_at = case.closed_at
    case.title = "Closure invariant updated"
    db.commit()
    db.refresh(case)
    assert case.closed_at == first_closed_at

    unsupported = Case(status="CLOSED_UNSUPPORTED", title="Unsupported terminal case")
    db.add(unsupported)
    db.commit()
    db.refresh(unsupported)
    assert unsupported.closed_at is not None


def test_verified_outcome_closes_case_and_handoff_exposes_technical_close_time(client, db):
    case_id = _awaiting_execution(client)
    resolved = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 8.99,
            "verified_by_user": True,
            "resolved_on": "2026-09-15",
            "resolution_channel": "bank_or_card_refund",
            "non_monetary_result": None,
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["case_status"] == "RESOLVED"

    db.expire_all()
    case = db.get(Case, case_id)
    outcome = db.scalar(select(Outcome).where(Outcome.case_id == case_id))
    assert case is not None and outcome is not None
    assert case.closed_at is not None
    assert outcome.resolved_at is not None
    # Both are technical persistence timestamps, while resolved_on remains the real date.
    assert abs((case.closed_at - outcome.resolved_at).total_seconds()) < 5

    handoff = client.get(f"/api/cases/{case_id}/handoff")
    assert handoff.status_code == 200, handoff.text
    body = handoff.json()
    assert body["case"]["status"] == "RESOLVED"
    assert body["case"]["closed_at"] is not None
    assert body["outcomes"][0]["resolved_on"] == "2026-09-15"
