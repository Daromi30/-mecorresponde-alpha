from pathlib import Path
import shutil
import subprocess
import tempfile

from sqlalchemy import select

from app.models import AuditEvent, Case, Outcome


STATIC = Path(__file__).parents[1] / "app" / "static"


def create_case(client):
    response = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_verified_non_monetary_resolution_preserves_execution_evidence(client, db):
    case_id = create_case(client)
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


def test_unknown_execution_date_remains_unknown(client, db):
    case_id = create_case(client)
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
    evidence = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "OUTCOME_EVIDENCE_RECORDED",
        )
    ).one()
    assert evidence.payload_json["resolved_on"] is None


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