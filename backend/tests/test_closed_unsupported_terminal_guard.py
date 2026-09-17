from pathlib import Path

from sqlalchemy import func, select

from app.models import Action, AuditEvent, Case, Decision, Fact


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_closed_unsupported_case_cannot_be_reopened_by_claimant_initial_routes(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Tengo un problema de consumo que quedó fuera del alcance automatizado"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]

    case = db.get(Case, case_id)
    assert case is not None
    case.status = "CLOSED_UNSUPPORTED"
    case.current_action_id = None
    case.current_decision_id = None
    db.commit()
    db.refresh(case)
    assert case.closed_at is not None

    counts_before = {
        "facts": db.scalar(select(func.count()).select_from(Fact).where(Fact.case_id == case_id)),
        "decisions": db.scalar(select(func.count()).select_from(Decision).where(Decision.case_id == case_id)),
        "actions": db.scalar(select(func.count()).select_from(Action).where(Action.case_id == case_id)),
        "audits": db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.case_id == case_id)),
    }

    fact_attempt = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": "purchase.buyer_is_consumer",
            "value": True,
            "state": "confirmed",
            "user_confirmed": True,
        },
    )
    diagnose_attempt = client.post(f"/api/cases/{case_id}/diagnose")
    prepare_attempt = client.post(f"/api/cases/{case_id}/prepare-claim")

    assert fact_attempt.status_code == 409, fact_attempt.text
    assert diagnose_attempt.status_code == 409, diagnose_attempt.text
    assert prepare_attempt.status_code == 409, prepare_attempt.text
    assert "locked in the current phase" in fact_attempt.json()["detail"]
    assert "locked in the current phase" in diagnose_attempt.json()["detail"]

    db.expire_all()
    stored = db.get(Case, case_id)
    assert stored is not None
    assert stored.status == "CLOSED_UNSUPPORTED"
    assert stored.closed_at is not None
    assert stored.current_action_id is None
    assert stored.current_decision_id is None

    counts_after = {
        "facts": db.scalar(select(func.count()).select_from(Fact).where(Fact.case_id == case_id)),
        "decisions": db.scalar(select(func.count()).select_from(Decision).where(Decision.case_id == case_id)),
        "actions": db.scalar(select(func.count()).select_from(Action).where(Action.case_id == case_id)),
        "audits": db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.case_id == case_id)),
    }
    assert counts_after == counts_before


def test_closed_unsupported_is_rendered_as_terminal_in_case_ui():
    script = (STATIC / "case_phase_guard.js").read_text(encoding="utf-8")
    assert "CLOSED_UNSUPPORTED" in script
    assert "fuera del alcance automatizado" in script
