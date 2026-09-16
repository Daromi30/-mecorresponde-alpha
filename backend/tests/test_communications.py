from sqlalchemy import select

from app.models import AuditEvent, Communication


def create_case(client, message):
    response = client.post("/api/cases", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_claim_submission_creates_outbound_communication_without_inventing_send_time(client, db):
    case_id = create_case(client, "Me cambié de compañía de luz y me siguen cobrando un mantenimiento")
    response = client.post(
        f"/api/cases/{case_id}/submission",
        json={
            "submitted_on": "2026-09-10",
            "channel": "web",
            "reference_number": "REF-SYNTHETIC-10",
        },
    )
    assert response.status_code == 200, response.text

    rows = db.scalars(select(Communication).where(Communication.case_id == case_id)).all()
    assert len(rows) == 1
    outbound = rows[0]
    assert outbound.direction == "OUTBOUND"
    assert outbound.channel == "web"
    assert outbound.reference_number == "REF-SYNTHETIC-10"
    assert outbound.sent_at is None
    assert outbound.received_at is None
    assert outbound.body is None

    # The date the user actually supplied is preserved exactly in the audit event;
    # the Communication row deliberately avoids inventing an hour/minute.
    audit = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "CLAIM_SUBMITTED",
        )
    ).one()
    assert audit.payload_json["submitted_on"] == "2026-09-10"
    assert audit.payload_json["reference"] == "REF-SYNTHETIC-10"


def test_company_response_is_stored_as_inbound_communication(client, db):
    case_id = create_case(client, "Me cambié de compañía de luz y me siguen cobrando un mantenimiento")
    text = "Denegamos la devolución porque el contrato de mantenimiento es independiente."
    response = client.post(f"/api/cases/{case_id}/responses", json={"text": text})
    assert response.status_code == 200

    inbound = db.scalars(
        select(Communication).where(
            Communication.case_id == case_id,
            Communication.direction == "INBOUND",
        )
    ).one()
    assert inbound.channel == "user_paste"
    assert inbound.body == text
    assert inbound.received_at is not None


def test_submission_and_response_form_a_structured_two_way_history(client, db):
    case_id = create_case(client, "Me cambié de compañía de luz y me siguen cobrando un mantenimiento")
    assert client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": "2026-09-11", "channel": "email"},
    ).status_code == 200
    assert client.post(
        f"/api/cases/{case_id}/responses",
        json={"text": "Aceptamos su reclamación y procederemos a devolver el importe."},
    ).status_code == 200

    rows = db.scalars(
        select(Communication).where(Communication.case_id == case_id)
    ).all()
    assert {row.direction for row in rows} == {"OUTBOUND", "INBOUND"}
    assert len(rows) == 2
