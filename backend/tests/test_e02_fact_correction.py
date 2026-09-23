from sqlalchemy import func, select

from app.models import AuditEvent, Case, Fact


KEY = "electricity.billing.correct_amount"


def _case(client):
    created = client.post("/api/cases", json={"message": "La factura de luz es incorrecta y me han cobrado de más"})
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    for key, value in (
        ("electricity.billing.invoice_date", "2026-07-01"),
        ("electricity.billing.billed_amount", 100),
        (KEY, 100),
    ):
        response = client.post(f"/api/cases/{case_id}/facts", json={"key": key, "value": value, "state": "confirmed"})
        assert response.status_code == 200, response.text
    response = client.post(f"/api/cases/{case_id}/diagnose")
    assert response.status_code == 200, response.text
    return case_id


def _correction(value=80, **changes):
    return {"key": KEY, "value": value, "state": "confirmed", "user_confirmed": True, "correction": True, **changes}


def _counts(db, case_id):
    facts = db.scalar(select(func.count()).select_from(Fact).where(Fact.case_id == case_id))
    events = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.case_id == case_id))
    return facts, events


def test_e02_correction_invalidates_then_rediagnoses_without_new_case(client, db):
    case_id = _case(client)
    initial = client.get(f"/api/cases/{case_id}").json()
    old_decision = initial["current_decision_id"]
    assert initial["current_action_id"] is None
    assert initial["decisions"][0]["claimable_amount"] == 0

    response = client.post(f"/api/cases/{case_id}/facts", json=_correction())
    assert response.status_code == 200, response.text
    reopened = client.get(f"/api/cases/{case_id}").json()
    assert reopened["id"] == case_id
    assert reopened["status"] == "INTAKE"
    assert reopened["current_decision_id"] is None
    assert reopened["current_action_id"] is None
    assert any(d["id"] == old_decision for d in reopened["decisions"])
    facts = [f for f in reopened["facts"] if f["key"] == KEY]
    assert len(facts) == 2
    assert facts[-1]["supersedes_fact_id"] == facts[0]["id"]
    assert facts[-1]["value"] == 80
    assert db.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.case_id == case_id, AuditEvent.event_type == "CURRENT_ANALYSIS_SUPERSEDED"
    )) == 1

    before_retry = _counts(db, case_id)
    retry = client.post(f"/api/cases/{case_id}/facts", json=_correction())
    assert retry.status_code == 200, retry.text
    assert retry.json()["fact_id"] == facts[-1]["id"]
    assert _counts(db, case_id) == before_retry

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["claimable_amount"] == 20
    active = client.get(f"/api/cases/{case_id}").json()
    assert active["id"] == case_id
    assert active["current_decision_id"] != old_decision
    assert len(active["decisions"]) == 2
    assert next(d for d in active["decisions"] if d["id"] == active["current_decision_id"])["claimable_amount"] == 20


def test_e02_correction_rejects_invalid_input_and_state_without_mutation(client, db):
    case_id = _case(client)
    before = _counts(db, case_id)
    before_case = client.get(f"/api/cases/{case_id}").json()
    bad = [
        _correction(80, key="electricity.billing.unknown_amount"),
        _correction("80"),
        _correction(True),
        _correction(-1),
        _correction(10**400),
        _correction(None),
        _correction(80, state="unknown"),
        _correction(80, user_confirmed=False),
        {"key": KEY, "correction": True},
        _correction(80, status="INTAKE"),
        _correction(80, current_decision_id="forged"),
        _correction(80, outcome={"recovered": 80}),
    ]
    for payload in bad:
        response = client.post(f"/api/cases/{case_id}/facts", json=payload)
        assert response.status_code in {409, 422}, (payload, response.text)
        assert _counts(db, case_id) == before
        assert client.get(f"/api/cases/{case_id}").json()["current_decision_id"] == before_case["current_decision_id"]

    case = db.get(Case, case_id)
    for status in ("RESOLVED", "CLOSED_UNSUPPORTED", "WAITING_RESPONSE"):
        case.status = status
        db.commit()
        response = client.post(f"/api/cases/{case_id}/facts", json=_correction())
        assert response.status_code == 409, response.text
        assert _counts(db, case_id) == before
        assert db.get(Case, case_id).status == status


def test_e02_correction_rejects_incoherent_current_decision(client, db):
    case_id = _case(client)
    other_id = _case(client)
    other_decision = client.get(f"/api/cases/{other_id}").json()["current_decision_id"]
    case = db.get(Case, case_id)
    before = _counts(db, case_id)
    for wrong_id in ("not-a-decision", other_decision):
        case.current_decision_id = wrong_id
        db.commit()
        response = client.post(f"/api/cases/{case_id}/facts", json=_correction())
        assert response.status_code == 409, response.text
        assert _counts(db, case_id) == before


def test_e02_correction_requires_existing_confirmed_user_evidence(client, db):
    case_id = _case(client)
    previous = db.scalars(select(Fact).where(Fact.case_id == case_id, Fact.key == KEY).order_by(Fact.created_at.desc())).first()
    previous.user_confirmed = False
    db.commit()
    before = _counts(db, case_id)
    response = client.post(f"/api/cases/{case_id}/facts", json=_correction())
    assert response.status_code == 409, response.text
    assert _counts(db, case_id) == before
