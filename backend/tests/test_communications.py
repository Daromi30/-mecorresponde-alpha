from sqlalchemy import select

from app.models import AuditEvent, Communication


def create_prepared_case(client):
    response = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert response.status_code == 200, response.text
    case_id = response.json()["id"]
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
    return case_id


def submit_case(client, submitted_on="2026-09-10", channel="web", reference="REF-SYNTHETIC-10"):
    case_id = create_prepared_case(client)
    response = client.post(
        f"/api/cases/{case_id}/submission",
        json={
            "submitted_on": submitted_on,
            "channel": channel,
            "reference_number": reference,
        },
    )
    assert response.status_code == 200, response.text
    return case_id


def test_claim_submission_creates_outbound_communication_without_inventing_send_time(client, db):
    case_id = submit_case(client)

    rows = db.scalars(select(Communication).where(Communication.case_id == case_id)).all()
    assert len(rows) == 1
    outbound = rows[0]
    assert outbound.direction == "OUTBOUND"
    assert outbound.channel == "web"
    assert outbound.reference_number == "REF-SYNTHETIC-10"
    assert outbound.sent_at is None
    assert outbound.received_at is None
    assert outbound.body is None

    audit = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "CLAIM_SUBMITTED",
        )
    ).one()
    assert audit.payload_json["submitted_on"] == "2026-09-10"
    assert audit.payload_json["reference"] == "REF-SYNTHETIC-10"


def test_company_response_is_stored_as_inbound_communication_with_evidence_metadata(client, db):
    case_id = submit_case(client)
    text = "Denegamos la devolución porque el contrato de mantenimiento es independiente."
    response = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": text,
            "received_on": "2026-09-12",
            "channel": "email",
            "reference_number": "RESP-2",
        },
    )
    assert response.status_code == 200, response.text

    inbound = db.scalars(
        select(Communication).where(
            Communication.case_id == case_id,
            Communication.direction == "INBOUND",
        )
    ).one()
    assert inbound.channel == "email"
    assert inbound.reference_number == "RESP-2"
    assert inbound.body == text
    assert inbound.received_at is not None

    audit = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "COMPANY_RESPONSE_RECORDED",
        )
    ).one()
    assert audit.payload_json["received_on"] == "2026-09-12"


def test_submission_and_response_form_a_structured_two_way_history(client, db):
    case_id = submit_case(client, submitted_on="2026-09-11", channel="email", reference=None)
    assert client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos su reclamación y procederemos a devolver el importe.",
            "received_on": "2026-09-12",
            "channel": "email",
        },
    ).status_code == 200

    rows = db.scalars(
        select(Communication).where(Communication.case_id == case_id)
    ).all()
    assert {row.direction for row in rows} == {"OUTBOUND", "INBOUND"}
    assert len(rows) == 2
