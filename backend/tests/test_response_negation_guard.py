import pytest
from sqlalchemy import func, select

from app.engine.gateway import DeterministicAlphaGateway
from app.models import Action, AuditEvent, Case, Communication


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Rechazamos su reclamación y no devolveremos los 50 euros solicitados.", "DENIAL"),
        ("No aceptamos su reclamación.", "DENIAL"),
        ("No procedemos a devolver el importe.", "DENIAL"),
        ("No devolvemos una parte del importe solicitado.", "DENIAL"),
        ("Aceptamos la recepción de su reclamación, pero no aceptamos la devolución.", "DENIAL"),
        ("Hemos recibido su solicitud; no confirmamos la devolución.", "UNKNOWN"),
        ("Aceptamos su reclamación, pero no la devolución.", "UNKNOWN"),
        ("Aceptamos su reclamación, pero no devolveremos el importe.", "UNKNOWN"),
        ("Aceptamos una parte del importe, pero no aceptamos el resto.", "PARTIAL"),
        ("Aceptamos su reclamación y devolveremos el importe.", "ACCEPTANCE"),
    ],
)
def test_response_text_never_turns_a_negation_into_acceptance(text, expected):
    assert DeterministicAlphaGateway().analyze_response(text)["type"] == expected


def test_explicit_denial_never_opens_execution_or_duplicates_initial_claim(client, db):
    created = client.post("/api/cases", json={"message": "La factura eléctrica me ha cobrado de más"})
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    for key, value in {
        "electricity.billing.invoice_date": "2026-07-01",
        "electricity.billing.billed_amount": 150.0,
        "electricity.billing.correct_amount": 100.0,
    }.items():
        fact = client.post(
            f"/api/cases/{case_id}/facts",
            json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
        )
        assert fact.status_code == 200, fact.text
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 200
    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": "2026-09-10", "channel": "web_form", "reference_number": "SYNTHETIC-DENIAL"},
    )
    assert submitted.status_code == 200, submitted.text

    response_payload = {
        "text": "Rechazamos su reclamación y no devolveremos los 50 euros solicitados.",
        "received_on": "2026-09-12",
        "channel": "web_portal",
        "reference_number": "SYNTHETIC-REJECTION",
    }
    response = client.post(f"/api/cases/{case_id}/responses/evidenced", json=response_payload)
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["type"] == "DENIAL"
    assert response.json()["case_status"] == "HUMAN_REVIEW"

    db.expire_all()
    case = db.get(Case, case_id)
    current = db.get(Action, case.current_action_id)
    assert current.type == "HUMAN_REVIEW"
    assert not db.scalars(
        select(Action).where(Action.case_id == case_id, Action.type == "VERIFY_EXECUTION")
    ).all()
    duplicate = client.post(f"/api/cases/{case_id}/responses/evidenced", json=response_payload)
    assert duplicate.status_code == 409
    assert db.scalar(select(func.count()).select_from(Communication).where(
        Communication.case_id == case_id, Communication.direction == "OUTBOUND"
    )) == 1
    assert db.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.case_id == case_id, AuditEvent.event_type == "CLAIM_SUBMITTED"
    )) == 1
