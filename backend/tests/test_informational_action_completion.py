from pathlib import Path

from sqlalchemy import select

from app.models import AuditEvent


STATIC = Path(__file__).parents[1] / "app" / "static"


def _fact(client, case_id: str, key: str, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def test_informational_diagnosis_completes_action_without_faking_resolution_and_reopens_on_new_fact(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "La factura de luz es incorrecta y me han cobrado de más"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]

    _fact(client, case_id, "electricity.billing.invoice_date", "2026-07-01")
    _fact(client, case_id, "electricity.billing.billed_amount", 100)
    _fact(client, case_id, "electricity.billing.correct_amount", 100)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    action_id = diagnosis.json()["action_id"]

    body = client.get(f"/api/cases/{case_id}").json()
    assert body["status"] == "DIAGNOSED"
    assert body["current_decision_id"] is not None
    assert body["current_action_id"] is None
    action = next(item for item in body["actions"] if item["id"] == action_id)
    assert action["type"] == "EXPLAIN_NO_OVERBILLING"
    assert action["status"] == "COMPLETED"

    next_question = client.get(f"/api/cases/{case_id}/next-question")
    assert next_question.status_code == 200, next_question.text
    assert next_question.json() == {"done": True, "question": None, "field": None}

    audit = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "INFORMATIONAL_ACTION_COMPLETED",
        )
        .order_by(AuditEvent.created_at.desc())
    )
    assert audit is not None
    assert audit.payload_json["action_id"] == action_id
    assert audit.payload_json["action_type"] == "EXPLAIN_NO_OVERBILLING"

    # A later verified fact legitimately invalidates the old conclusion and reopens intake.
    _fact(client, case_id, "electricity.billing.correct_amount", 80)
    reopened = client.get(f"/api/cases/{case_id}").json()
    assert reopened["status"] == "INTAKE"
    assert reopened["current_decision_id"] is None
    assert reopened["current_action_id"] is None

    updated = client.post(f"/api/cases/{case_id}/diagnose")
    assert updated.status_code == 200, updated.text
    assert updated.json()["claimable_amount"] == 20
    active = client.get(f"/api/cases/{case_id}").json()
    assert active["status"] == "DIAGNOSED"
    assert active["current_action_id"] is not None
    current = next(item for item in active["actions"] if item["id"] == active["current_action_id"])
    assert current["status"] == "OPEN"


def test_no_action_diagnosis_is_explicit_in_claimant_ui():
    next_step = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    progress = (STATIC / "case_progress.js").read_text(encoding="utf-8")
    assert "if (!current)" in next_step
    assert "Análisis concluido · no hay una acción adicional" in next_step
    assert "status === 'DIAGNOSED' && hasCurrentDecision() && !caseData.current_action_id" in progress
    assert "diagnosedWithoutPendingAction" in progress
