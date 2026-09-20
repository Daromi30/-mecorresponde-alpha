from __future__ import annotations

from datetime import date
import pytest
from sqlalchemy import func, select

from app import services_v2 as svc
from app.evidence_context import company_response_evidence_context
from app.models import AIRun, AuditEvent, Case, Communication, Evidence, Fact


def _count(db, model, case_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(model.case_id == case_id)) or 0)


def _case(client, db) -> Case:
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado un servicio adicional de luz que no contraté"},
    )
    assert created.status_code == 200, created.text
    case = db.get(Case, created.json()["id"])
    assert case is not None
    return case


def _two_argument_response(_text: str) -> dict:
    return {
        "type": "DENIAL",
        "arguments": ["CONSENT_EVIDENCE", "DIFFERENT_DEBTS"],
    }


def test_company_response_persists_all_derived_arguments_together(client, db, monkeypatch):
    case = _case(client, db)
    monkeypatch.setattr(svc.gateway, "analyze_response", _two_argument_response)

    with company_response_evidence_context(
        received_on=date(2026, 9, 12),
        channel="email",
        reference_number="RESP-ATOMIC",
    ):
        result = svc.analyze_company_response(db, case, "La empresa invoca consentimiento y deudas distintas")
    assert result["type"] == "DENIAL"

    db.expire_all()
    facts = db.scalars(
        select(Fact).where(Fact.case_id == case.id, Fact.created_by == "company")
    ).all()
    assert {fact.key for fact in facts} >= {
        "company.asserts_consent",
        "company.asserts_different_debts",
    }
    assert all(fact.state == "asserted" for fact in facts)
    assert all(fact.user_confirmed is False for fact in facts)
    assert _count(db, Communication, case.id) == 1
    communication = db.scalars(
        select(Communication).where(
            Communication.case_id == case.id,
            Communication.direction == "INBOUND",
        )
    ).one()
    assert communication.occurred_on == date(2026, 9, 12)
    assert communication.channel == "email"
    assert communication.reference_number == "RESP-ATOMIC"
    recorded = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case.id,
            AuditEvent.event_type == "COMPANY_RESPONSE_RECORDED",
        )
    ).one()
    assert recorded.payload_json["communication_id"] == communication.id
    assert recorded.payload_json["received_on"] == "2026-09-12"
    assert recorded.payload_json["channel"] == "email"
    assert recorded.payload_json["reference"] == "RESP-ATOMIC"
    assert _count(db, AIRun, case.id) >= 2  # classification + response analysis


def test_company_response_failure_rolls_back_entire_response_snapshot(client, db, monkeypatch):
    case = _case(client, db)
    original_status = case.status
    monkeypatch.setattr(svc.gateway, "analyze_response", _two_argument_response)

    before = {
        "facts": _count(db, Fact, case.id),
        "evidence": _count(db, Evidence, case.id),
        "communications": _count(db, Communication, case.id),
        "ai_runs": _count(db, AIRun, case.id),
        "audits": _count(db, AuditEvent, case.id),
    }

    real_upsert = svc.upsert_fact
    calls = {"count": 0}

    def fail_second_company_fact(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("synthetic second company fact failure")
        return real_upsert(*args, **kwargs)

    monkeypatch.setattr(svc, "upsert_fact", fail_second_company_fact)

    with pytest.raises(RuntimeError, match="synthetic second company fact failure"):
        with company_response_evidence_context(
            received_on=date(2026, 9, 12),
            channel="email",
            reference_number="RESP-ROLLBACK",
        ):
            svc.analyze_company_response(db, case, "La empresa invoca consentimiento y deudas distintas")

    db.expire_all()
    restored = db.get(Case, case.id)
    assert restored is not None
    assert restored.status == original_status
    assert _count(db, Fact, case.id) == before["facts"]
    assert _count(db, Evidence, case.id) == before["evidence"]
    assert _count(db, Communication, case.id) == before["communications"]
    assert _count(db, AIRun, case.id) == before["ai_runs"]
    assert _count(db, AuditEvent, case.id) == before["audits"]
