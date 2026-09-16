from datetime import date

from sqlalchemy import select

from app.models import Communication


PASSWORD = "strong-password-for-communication-date"


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def test_real_communication_dates_survive_persistence_handoff_and_account_export(client, db):
    registered = client.post(
        "/api/auth/register",
        json={"email": "chronology@example.com", "password": PASSWORD},
    )
    assert registered.status_code == 201, registered.text

    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    claimed = client.post(f"/api/cases/{case_id}/claim")
    assert claimed.status_code == 200, claimed.text

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
            "reference_number": "SUB-REAL-DATE",
        },
    )
    assert submitted.status_code == 200, submitted.text

    outbound = db.scalars(
        select(Communication).where(
            Communication.case_id == case_id,
            Communication.direction == "OUTBOUND",
        )
    ).one()
    assert outbound.occurred_on == date(2026, 9, 10)
    assert outbound.sent_at is None

    answered = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos su reclamación y procederemos a devolver el importe.",
            "received_on": "2026-09-12",
            "channel": "email",
            "reference_number": "RESP-REAL-DATE",
        },
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["analysis"]["type"] == "ACCEPTANCE"

    db.expire_all()
    inbound = db.scalars(
        select(Communication).where(
            Communication.case_id == case_id,
            Communication.direction == "INBOUND",
        )
    ).one()
    assert inbound.occurred_on == date(2026, 9, 12)

    handoff = client.get(f"/api/cases/{case_id}/handoff")
    assert handoff.status_code == 200, handoff.text
    handoff_rows = handoff.json()["communications"]
    by_direction = {row["direction"]: row for row in handoff_rows}
    assert by_direction["OUTBOUND"]["occurred_on"] == "2026-09-10"
    assert by_direction["INBOUND"]["occurred_on"] == "2026-09-12"

    exported = client.get("/api/auth/export")
    assert exported.status_code == 200, exported.text
    exported_case = next(row for row in exported.json()["cases"] if row["id"] == case_id)
    export_by_direction = {row["direction"]: row for row in exported_case["communications"]}
    assert export_by_direction["OUTBOUND"]["occurred_on"] == "2026-09-10"
    assert export_by_direction["INBOUND"]["occurred_on"] == "2026-09-12"


def test_unknown_company_response_date_remains_unknown_in_normalized_communication(client, db):
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

    answered = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos su reclamación y procederemos a devolver el importe.",
            "received_on": None,
            "channel": "email",
        },
    )
    assert answered.status_code == 200, answered.text

    db.expire_all()
    inbound = db.scalars(
        select(Communication).where(
            Communication.case_id == case_id,
            Communication.direction == "INBOUND",
        )
    ).one()
    assert inbound.occurred_on is None
