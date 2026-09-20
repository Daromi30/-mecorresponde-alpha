from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Action, Case, Document, Evidence, Fact
from app.routers import cases_v2 as case_routes


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _count(db, model, case_id: str) -> int:
    return int(
        db.scalar(select(func.count()).select_from(model).where(model.case_id == case_id))
        or 0
    )


def test_document_fact_response_failure_rolls_back_fact_evidence_and_analysis_invalidation(
    client, db, monkeypatch
):
    created = client.post(
        "/api/cases",
        json={"message": "La factura eléctrica me ha cobrado de más"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    _fact(client, case_id, "electricity.billing.invoice_date", "2026-07-01")
    _fact(client, case_id, "electricity.billing.billed_amount", 150.0)
    _fact(client, case_id, "electricity.billing.correct_amount", 100.0)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    decision_id = diagnosis.json()["decision_id"]
    action_id = diagnosis.json()["action_id"]

    document = Document(
        case_id=case_id,
        storage_key=f"synthetic/{case_id}/factura.txt",
        original_filename="factura.txt",
        mime_type="text/plain",
        sha256="a" * 64,
        contains_sensitive_data=False,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    before_facts = _count(db, Fact, case_id)
    before_evidence = _count(db, Evidence, case_id)

    def fail_next_question(*_args, **_kwargs):
        raise RuntimeError("synthetic document next-question failure")

    monkeypatch.setattr(case_routes, "get_next_question", fail_next_question)

    with pytest.raises(RuntimeError, match="synthetic document next-question failure"):
        client.post(
            f"/api/cases/{case_id}/documents/{document.id}/confirm-fact",
            json={
                "key": "electricity.billing.correct_amount",
                "value": 90.0,
                "locator": "linea 3",
                "excerpt": "Importe correcto 90 EUR",
                "materiality": "critical",
            },
        )

    db.rollback()
    db.expire_all()
    restored = db.get(Case, case_id)
    assert restored is not None
    assert restored.status == "DIAGNOSED"
    assert restored.current_decision_id == decision_id
    assert restored.current_action_id == action_id
    action = db.get(Action, action_id)
    assert action is not None and action.status == "OPEN"
    assert _count(db, Fact, case_id) == before_facts
    assert _count(db, Evidence, case_id) == before_evidence
