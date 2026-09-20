from datetime import date
from pathlib import Path
import pytest
import shutil
import subprocess
import tempfile

from sqlalchemy import select

from app.models import Action, AuditEvent, Case, Outcome
from app.routers import cases_v2 as cases_router_module


STATIC = Path(__file__).parents[1] / "app" / "static"


def create_case_awaiting_execution(client):
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
    assert accepted.json()["analysis"]["type"] == "ACCEPTANCE"
    return case_id


def test_verified_non_monetary_resolution_preserves_execution_evidence(client, db):
    case_id = create_case_awaiting_execution(client)
    response = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 0,
            "verified_by_user": True,
            "resolved_on": "2026-09-15",
            "resolution_channel": "cancellation",
            "non_monetary_result": "La empresa canceló el servicio y confirmó que no habrá más cargos.",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["case_status"] == "RESOLVED"
    assert response.json()["resolved_on"] == "2026-09-15"

    outcome = db.scalar(select(Outcome).where(Outcome.case_id == case_id))
    assert outcome is not None
    assert outcome.amount_recovered == 0
    assert outcome.verified_by_user is True
    assert outcome.resolution_channel == "cancellation"
    assert outcome.resolved_on == date(2026, 9, 15)
    assert outcome.resolved_at is not None
    assert "no habrá más cargos" in outcome.non_monetary_result

    evidence = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "OUTCOME_EVIDENCE_RECORDED",
        )
    ).one()
    assert evidence.payload_json["resolved_on"] == "2026-09-15"
    assert evidence.payload_json["resolution_channel"] == "cancellation"
    assert evidence.payload_json["amount_recovered"] == 0
    assert evidence.payload_json["has_non_monetary_result"] is True

    timeline = client.get(f"/api/cases/{case_id}/timeline")
    assert timeline.status_code == 200, timeline.text
    resolution = next(
        item for item in timeline.json()["events"] if item["type"] == "RESOLUTION_VERIFIED"
    )
    assert resolution["resolved_on"] == "2026-09-15"
    assert resolution["at"] is not None

    handoff = client.get(f"/api/cases/{case_id}/handoff")
    assert handoff.status_code == 200, handoff.text
    exported = handoff.json()["outcomes"][0]
    assert exported["resolved_on"] == "2026-09-15"
    assert exported["resolved_at"] is not None


def test_unknown_execution_date_remains_unknown(client, db):
    case_id = create_case_awaiting_execution(client)
    response = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 35.5,
            "verified_by_user": True,
            "resolved_on": None,
            "resolution_channel": "bank_or_card_refund",
            "non_monetary_result": None,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["resolved_on"] is None
    outcome = db.scalar(select(Outcome).where(Outcome.case_id == case_id))
    assert outcome is not None
    assert outcome.resolved_on is None
    assert outcome.resolved_at is not None
    evidence = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "OUTCOME_EVIDENCE_RECORDED",
        )
    ).one()
    assert evidence.payload_json["resolved_on"] is None



def test_outcome_evidence_failure_rolls_back_case_action_outcome_and_audit(client, db, monkeypatch):
    case_id = create_case_awaiting_execution(client)
    before_case = db.get(Case, case_id)
    assert before_case is not None
    assert before_case.status == "RESOLVED_PENDING_EXECUTION"
    action_id = before_case.current_action_id
    assert action_id is not None
    before_action = db.get(Action, action_id)
    assert before_action is not None
    assert before_action.type == "VERIFY_EXECUTION"
    assert before_action.status == "OPEN"

    real_audit = cases_router_module.audit

    def fail_evidence_audit(db_session, audited_case_id, event_type, payload=None):
        if event_type == "OUTCOME_EVIDENCE_RECORDED":
            raise RuntimeError("synthetic outcome evidence failure")
        return real_audit(db_session, audited_case_id, event_type, payload)

    monkeypatch.setattr(cases_router_module, "audit", fail_evidence_audit)

    with pytest.raises(RuntimeError, match="synthetic outcome evidence failure"):
        client.post(
            f"/api/cases/{case_id}/outcome/evidenced",
            json={
                "result_type": "FAVORABLE",
                "amount_recovered": 35.5,
                "verified_by_user": True,
                "resolved_on": "2026-09-15",
                "resolution_channel": "bank_or_card_refund",
                "non_monetary_result": None,
            },
        )

    db.rollback()
    db.expire_all()
    restored_case = db.get(Case, case_id)
    assert restored_case is not None
    assert restored_case.status == "RESOLVED_PENDING_EXECUTION"
    assert restored_case.current_action_id == action_id
    restored_action = db.get(Action, action_id)
    assert restored_action is not None
    assert restored_action.status == "OPEN"
    assert db.scalar(select(Outcome).where(Outcome.case_id == case_id)) is None
    assert db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "OUTCOME_EVIDENCE_RECORDED",
        )
    ).all() == []

def test_outcome_evidence_ui_is_loaded_and_requires_detail_for_zero_cash_resolution():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "outcome_evidence.js").read_text(encoding="utf-8")
    assert "/demo/outcome_evidence.js" in loader
    assert "/outcome/evidenced" in script
    assert "outcomeResolvedOn" in script
    assert "outcomeChannel" in script
    assert "outcomeDetail" in script
    assert "amount <= 0 && detail.length < 3" in script
    assert "en lugar de convertir hoy en la fecha de resolución" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_outcome_evidence_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "outcome_evidence.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
