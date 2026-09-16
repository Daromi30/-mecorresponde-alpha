from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import func, select

from app.models import Action, AuditEvent, Case
from app.reviews import HumanReview


_matrix_path = Path(__file__).with_name("test_beta_acceptance_matrix.py")
_spec = importlib.util.spec_from_file_location("mcr_beta_acceptance_matrix_response", _matrix_path)
assert _spec and _spec.loader
_matrix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_matrix)
SCENARIOS = _matrix.SCENARIOS


def _fact(client, case_id: str, key: str, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": key,
            "value": value,
            "state": "confirmed",
            "user_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text


def _submitted_case(client, family: str, scenario: dict) -> str:
    created = client.post("/api/cases", json={"message": scenario["message"]})
    assert created.status_code == 200, f"{family}: {created.text}"
    body = created.json()
    assert body["family"] == family
    case_id = body["id"]

    for key, value in scenario["facts"].items():
        _fact(client, case_id, key, value)

    charges = scenario.get("charges")
    if charges:
        response = client.post(
            f"/api/cases/{case_id}/charges",
            json={"charges": charges},
        )
        assert response.status_code == 200, f"{family}: {response.text}"

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, f"{family}: {diagnosis.text}"
    assert diagnosis.json()["viability"] == "HIGH", (family, diagnosis.json())

    prepared = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert prepared.status_code == 200, f"{family}: {prepared.text}"
    assert prepared.json()["legal_basis"], family

    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={
            "submitted_on": "2026-09-10",
            "channel": "web_form",
            "reference_number": f"RESP-MATRIX-{family}",
        },
    )
    assert submitted.status_code == 200, f"{family}: {submitted.text}"
    assert client.get(f"/api/cases/{case_id}").json()["status"] == "WAITING_RESPONSE"
    return case_id


def test_every_beta_family_can_complete_favorable_response_and_verified_execution(client):
    for family, scenario in SCENARIOS.items():
        case_id = _submitted_case(client, family, scenario)

        response = client.post(
            f"/api/cases/{case_id}/responses/evidenced",
            json={
                "text": "Aceptamos su reclamación y procederemos a cumplir lo solicitado.",
                "received_on": "2026-09-12",
                "channel": "email",
                "reference_number": f"ACCEPT-{family}",
            },
        )
        assert response.status_code == 200, f"{family}: {response.text}"
        body = response.json()
        assert body["analysis"]["type"] == "ACCEPTANCE", (family, body)
        assert body["case_status"] == "RESOLVED_PENDING_EXECUTION", (family, body)

        pending = client.get(f"/api/cases/{case_id}")
        assert pending.status_code == 200, f"{family}: {pending.text}"
        pending_body = pending.json()
        current = next(
            action for action in pending_body["actions"]
            if action["id"] == pending_body["current_action_id"]
        )
        assert current["type"] == "VERIFY_EXECUTION", (family, current)
        assert current["status"] == "OPEN", (family, current)

        resolved = client.post(
            f"/api/cases/{case_id}/outcome/evidenced",
            json={
                "result_type": "FAVORABLE",
                "amount_recovered": 0,
                "verified_by_user": True,
                "resolved_on": "2026-09-13",
                "resolution_channel": "other",
                "non_monetary_result": "Cumplimiento sintético confirmado para prueba interna.",
            },
        )
        assert resolved.status_code == 200, f"{family}: {resolved.text}"
        assert resolved.json()["case_status"] == "RESOLVED", (family, resolved.json())
        assert client.get(f"/api/cases/{case_id}").json()["status"] == "RESOLVED", family


def test_partial_company_response_never_loops_back_to_a_second_initial_claim(client, db):
    for family, scenario in SCENARIOS.items():
        case_id = _submitted_case(client, family, scenario)

        response = client.post(
            f"/api/cases/{case_id}/responses/evidenced",
            json={
                "text": "Devolvemos una parte del importe reclamado; el resto queda rechazado.",
                "received_on": "2026-09-12",
                "channel": "email",
                "reference_number": f"PARTIAL-{family}",
            },
        )
        assert response.status_code == 200, f"{family}: {response.text}"
        body = response.json()
        assert body["analysis"]["type"] == "PARTIAL", (family, body)

        current_case = client.get(f"/api/cases/{case_id}")
        assert current_case.status_code == 200, f"{family}: {current_case.text}"
        case_body = current_case.json()
        assert case_body["status"] == "HUMAN_REVIEW", (family, case_body["status"], body)

        current_action = next(
            action for action in case_body["actions"]
            if action["id"] == case_body["current_action_id"]
        )
        assert current_action["type"] == "HUMAN_REVIEW", (family, current_action)
        assert current_action["status"] == "OPEN", (family, current_action)
        assert current_action["payload"].get("phase") == "POST_RESPONSE_ESCALATION", (
            family,
            current_action,
        )

        db.expire_all()
        case = db.get(Case, case_id)
        assert case is not None
        open_review = db.scalars(
            select(HumanReview).where(
                HumanReview.case_id == case_id,
                HumanReview.status == "OPEN",
                HumanReview.reason == "POST_DENIAL_ESCALATION_REVIEW",
            )
        ).first()
        assert open_review is not None, family

        ready_initial_actions = db.scalar(
            select(func.count())
            .select_from(Action)
            .where(
                Action.case_id == case_id,
                Action.type == "SUBMIT_INITIAL_CLAIM",
                Action.status == "READY",
            )
        )
        assert int(ready_initial_actions or 0) == 0, family

        submitted_events = db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.case_id == case_id,
                AuditEvent.event_type == "CLAIM_SUBMITTED",
            )
        )
        assert int(submitted_events or 0) == 1, family

        escalation = db.scalars(
            select(AuditEvent).where(
                AuditEvent.case_id == case_id,
                AuditEvent.event_type == "ESCALATION_REVIEW_REQUIRED",
            )
        ).first()
        assert escalation is not None, family
        payload = escalation.payload_json or {}
        assert payload.get("family") == family
        serialized = str(payload).lower()
        for prohibited in ("court", "tribunal", "arbit", "regulator", "authority", "deadline", "success_probability"):
            assert prohibited not in serialized, (family, prohibited, payload)
