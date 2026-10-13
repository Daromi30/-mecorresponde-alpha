"""Synthetic-only tests: the production private-beta interlock remains false."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth_models import Reviewer
from app.backoffice_auth import create_reviewer
from app.config import settings
from app.family_manifest import FAMILY_MANIFEST
from app.models import Action, Case, Decision, Fact
from app.engine.c01 import evaluate_c01
from app.engine.common import FactValue
from app.engine.e02 import evaluate_e02a
from app.engine.questions import next_question
from app.private_beta_fields import FIELD_SCHEMA
from app.services_v2 import latest_facts
from app.private_beta_release import RELEASE_REASON, ensure_release_review, release_approved
from app.reviews import HumanReview
from app import real_beta_gate as gate
from app import services_v2 as svc


CASES = {
    "E02-A": [
        ("electricity.billing.billing_period", "2026-09"),
        ("electricity.billing.invoice_date", "2026-10-01"),
        ("electricity.billing.billed_amount", 120),
        ("electricity.billing.correct_amount", 80),
    ],
    "C01": [
        ("purchase.buyer_is_consumer", True),
        ("purchase.seller_is_business", True),
        ("purchase.second_hand", False),
        ("purchase.delivery_date", "2026-08-01"),
        ("purchase.defect_manifested_date", "2026-09-01"),
        ("purchase.nonconformity_reported", True),
        ("purchase.accidental_damage_or_misuse", False),
        ("purchase.price", 150),
    ],
}


@pytest.fixture
def future_test_gate(monkeypatch):
    monkeypatch.setattr(settings, "real_beta_enabled", "true")
    monkeypatch.setattr(settings, "real_beta_allowlist", "E02-A,C01")
    monkeypatch.setattr(gate, "technical_prerequisites_ready", lambda: True)
    assert gate.REAL_BETA_LAUNCH_REVIEW_COMPLETE is False


def _admit(client, db, family):
    reviewer = create_reviewer(db, "testoperator", "synthetic-operator-password", "operator")
    db.commit()
    login = client.post("/api/backoffice-auth/login", json={
        "login_id": "testoperator", "password": "synthetic-operator-password",
    })
    assert login.status_code == 200
    invite = client.post("/api/admin/real-beta/invitations", json={"expires_in_hours": 24})
    assert invite.status_code == 201
    client.historical_account(f"release-{family.lower()}@example.com", "synthetic-strong-password")
    accept = client.post("/api/real-beta/invitations/accept", json={"token": invite.json()["token"]})
    assert accept.status_code == 200
    created = client.post("/api/real-beta/cases", json={
        "family": family, "age_18_plus_attested": True,
    })
    assert created.status_code == 201, created.text
    assert created.json()["family"] == family
    assert created.json()["raw_intake"] == f"PRIVATE_REAL_BETA:{family}"
    assert created.json()["title"] == FAMILY_MANIFEST[family].title
    return created.json()["id"], reviewer, CASES[family]


def _record_required_facts(client, case_id, facts):
    for key, value in facts:
        response = client.post(f"/api/cases/{case_id}/facts", json={
            "key": key, "value": value, "state": "confirmed", "user_confirmed": True,
        })
        assert response.status_code == 200, response.text


def _assign_and_approve(client, review, reviewer):
    assigned = client.post(f"/api/admin/reviews/{review.id}/assign", json={"reviewer_id": reviewer.id})
    assert assigned.status_code == 200, assigned.text
    assert client.post("/api/backoffice-auth/logout").status_code == 200
    assert client.post(f"/api/admin/reviews/{review.id}/approve-release").status_code == 401
    assert client.post("/api/backoffice-auth/login", json={
        "login_id": "testoperator", "password": "synthetic-operator-password",
    }).status_code == 200
    approved = client.post(f"/api/admin/reviews/{review.id}/approve-release")
    assert approved.status_code == 200, approved.text
    return approved


@pytest.mark.parametrize("family", ["E02-A", "C01"])
def test_private_release_requires_assigned_reviewer_for_current_decision(
    client, db, future_test_gate, family,
):
    case_id, reviewer, facts = _admit(client, db, family)
    _record_required_facts(client, case_id, facts)
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["status"] == "PENDING_HUMAN_REVIEW"
    assert diagnosis.json()["action_id"] is None
    case = db.get(Case, case_id)
    review = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case_id, HumanReview.reason == RELEASE_REASON,
    ))
    assert review is not None and review.status == "OPEN"
    assert case.status == "HUMAN_REVIEW"
    decision = db.get(Decision, case.current_decision_id)
    action = db.get(Action, case.current_action_id)
    ensure_release_review(db, case, decision, action)
    assert len(db.scalars(select(HumanReview).where(
        HumanReview.case_id == case_id, HumanReview.reason == RELEASE_REASON,
    )).all()) == 1

    detail = client.get(f"/api/cases/{case_id}")
    assert detail.status_code == 200
    assert detail.json()["actions"] == detail.json()["decisions"] == []
    exported = client.get("/api/auth/export")
    assert exported.status_code == 200
    exported_case = next(row for row in exported.json()["cases"] if row["id"] == case_id)
    assert exported_case["raw_intake"] == f"PRIVATE_REAL_BETA:{family}"
    assert "Mi nombre" not in str(exported_case)
    assert exported_case["actions"] == exported_case["decisions"] == []
    assert exported_case["calculations"] == exported_case["rule_evaluations"] == []
    assert exported_case["audit_events"] == exported_case["ai_runs"] == []
    legal_sources = client.get(f"/api/cases/{case_id}/legal-sources")
    assert legal_sources.status_code == 200
    assert legal_sources.json() == {"decision_id": None, "sources": []}
    quality = client.get(f"/api/cases/{case_id}/quality")
    assert quality.status_code == 200
    assert quality.json()["gates"]["current_decision_id"] is None
    assert quality.json()["gates"]["rules_evaluated"] == 0
    assert client.get(f"/api/cases/{case_id}/handoff").status_code == 409
    internal_draft = client.get(f"/api/admin/cases/{case_id}/handoff")
    assert internal_draft.status_code == 200
    assert internal_draft.json()["latest_decision"] is not None
    assert internal_draft.json()["case"]["raw_intake"] == f"PRIVATE_REAL_BETA:{family}"
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 409
    assert client.post(f"/api/cases/{case_id}/submission", json={"submitted_on": "2026-09-01"}).status_code == 409
    upload = client.post(
        f"/api/cases/{case_id}/documents",
        files={"file": ("synthetic.txt", b"synthetic only", "text/plain")},
    )
    assert upload.status_code == 409
    assert client.post(f"/api/cases/{case_id}/reviews/{review.id}/complete", json={
        "reviewer_decision": "I approve myself",
    }).status_code == 403
    assert client.post(f"/api/admin/reviews/{review.id}/complete", json={
        "reviewer_decision": "generic note",
    }).status_code == 409

    _assign_and_approve(client, review, reviewer)
    assert client.post(f"/api/admin/reviews/{review.id}/approve-release").status_code == 409
    released = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert released.status_code == 200, released.text
    assert client.get(f"/api/cases/{case_id}/handoff").status_code == 200


def test_fact_change_and_rediagnosis_cannot_reuse_prior_release_approval(
    client, db, future_test_gate,
):
    case_id, reviewer, facts = _admit(client, db, "E02-A")
    _record_required_facts(client, case_id, facts)
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200
    case = db.get(Case, case_id)
    first_decision_id = case.current_decision_id
    review = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case_id,
        HumanReview.reason == RELEASE_REASON,
        HumanReview.status == "OPEN",
    ))
    _assign_and_approve(client, review, reviewer)
    assert release_approved(db, case)

    changed = client.post(f"/api/cases/{case_id}/facts", json={
        "key": "electricity.billing.billed_amount",
        "value": 130,
        "state": "confirmed",
        "user_confirmed": True,
    })
    assert changed.status_code == 200, changed.text
    db.expire_all()
    case = db.get(Case, case_id)
    assert case.current_decision_id is None
    assert not release_approved(db, case)

    rediagnosed = client.post(f"/api/cases/{case_id}/diagnose")
    assert rediagnosed.status_code == 200, rediagnosed.text
    assert rediagnosed.json()["status"] == "PENDING_HUMAN_REVIEW"
    assert rediagnosed.json()["decision_id"] is None
    assert rediagnosed.json()["action_id"] is None
    db.expire_all()
    case = db.get(Case, case_id)
    assert case.current_decision_id != first_decision_id
    assert not release_approved(db, case)
    reviews = db.scalars(select(HumanReview).where(
        HumanReview.case_id == case_id,
        HumanReview.reason == RELEASE_REASON,
    )).all()
    assert sorted(row.status for row in reviews) == ["COMPLETED", "OPEN"]
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 409
    assert client.get(f"/api/cases/{case_id}/handoff").status_code == 409


@pytest.mark.parametrize("family,wrong_key", [
    ("E02-A", "electricity.billing.unlisted"),
    ("C01", "purchase.unlisted"),
])
def test_private_fact_allowlist_rejects_unknown_fields(client, db, future_test_gate, family, wrong_key):
    case_id, _reviewer, _facts = _admit(client, db, family)
    response = client.post(f"/api/cases/{case_id}/facts", json={"key": wrong_key, "value": "secret"})
    assert response.status_code == 422
    assert client.post(f"/api/cases/{case_id}/facts", json={
        "key": CASES[family][0][0], "value": {"unexpected": "shape"},
    }).status_code == 422


def test_adult_attestation_is_strict_and_does_not_open_the_production_interlock(client, db, future_test_gate):
    assert gate.REAL_BETA_LAUNCH_REVIEW_COMPLETE is False
    case_id, _reviewer, _facts = _admit(client, db, "E02-A")
    assert db.get(Case, case_id) is not None
    for value in (None, False, "true", 1):
        payload = {"family": "E02-A"}
        if value is not None:
            payload["age_18_plus_attested"] = value
        assert client.post("/api/real-beta/cases", json=payload).status_code == 422
    assert gate.REAL_BETA_LAUNCH_REVIEW_COMPLETE is False


def test_true_attestation_alone_never_opens_real_beta():
    assert len(FAMILY_MANIFEST) == 26
    assert gate.REAL_BETA_LAUNCH_REVIEW_COMPLETE is False
    assert gate.technical_prerequisites_ready() is False
    assert gate.real_beta_gate_open() is False


def test_e02_period_without_day_or_correct_amount_can_reach_human_review(
    client, db, future_test_gate,
):
    case_id, _reviewer, _facts = _admit(client, db, "E02-A")
    first = client.get(f"/api/cases/{case_id}/next-question").json()
    assert first["field"] == "electricity.billing.billing_period"
    assert first["input_type"] == "month"
    _record_required_facts(client, case_id, [
        ("electricity.billing.billing_period", "2026-09"),
        ("electricity.billing.billed_amount", 120),
    ])
    exact_question = client.get(f"/api/cases/{case_id}/next-question").json()
    assert exact_question["field"] == "electricity.billing.invoice_date"
    assert exact_question["optional"] is True
    assert client.post(f"/api/cases/{case_id}/facts", json={
        "key": "electricity.billing.invoice_date", "value": None,
        "state": "unknown", "user_confirmed": False,
    }).status_code == 200
    assert client.get(f"/api/cases/{case_id}/next-question").json()["done"] is True
    diagnosed = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosed.status_code == 200
    assert diagnosed.json()["status"] == "PENDING_HUMAN_REVIEW"
    decision = db.get(Decision, db.get(Case, case_id).current_decision_id)
    assert decision.claimable_amount is None
    assert decision.viability == "INSUFFICIENT_INFORMATION"
    assert "electricity.billing.correct_amount" not in latest_facts(db, case_id)
    # Protected review owns the next transition; no participant question bypasses it.
    assert client.get(f"/api/cases/{case_id}/next-question").json()["done"] is True
    exact_fact = next(f for f in client.get(f"/api/cases/{case_id}").json()["facts"]
                      if f["key"] == "electricity.billing.invoice_date")
    assert exact_fact["value"] is None and exact_fact["state"] == "unknown"


@pytest.mark.parametrize("period,expected", [
    ("2026-05", "PENDING"),
    ("2026-06", "PENDING"),
    ("2026-07", "PENDING"),
])
def test_e02_month_precision_never_becomes_a_fabricated_date(period, expected):
    facts = {
        "electricity.billing.billing_period": FactValue(period),
        "electricity.billing.billed_amount": FactValue(120),
    }
    result = evaluate_e02a(facts, private_beta=True)
    assert result.rule_result == expected
    assert "electricity.billing.invoice_date" not in facts
    assert result.calculation is None
    assert "insufficient_date_precision" in result.failed_conditions
    assert result.claimable_amount is None


@pytest.mark.parametrize("exact,expected", [
    ("2026-06-11", "OUT_OF_VALIDITY"),
    ("2026-06-12", "APPLIES"),
])
def test_e02_exact_date_optional_and_respects_rule_boundary(exact, expected):
    facts = {
        "electricity.billing.billing_period": FactValue("2026-06"),
        "electricity.billing.invoice_date": FactValue(exact),
        "electricity.billing.billed_amount": FactValue(120, state="confirmed", source="user"),
        "electricity.billing.correct_amount": FactValue(80, state="confirmed", source="user"),
    }
    result = evaluate_e02a(facts, private_beta=True)
    assert result.rule_result == expected
    if expected == "APPLIES":
        assert result.viability == "MEDIUM"  # User-supplied correct amount is not independently verified.
        assert result.claimable_amount == 40
        assert any(c["type"] == "CORRECT_AMOUNT_MAY_BE_DISPUTED" for c in result.counterarguments)


def test_e02_unknown_correct_amount_never_invents_quantification():
    facts = {
        "electricity.billing.billing_period": FactValue("2026-09"),
        "electricity.billing.billed_amount": FactValue(120),
        "electricity.billing.correct_amount": FactValue(None, state="unknown"),
    }
    result = evaluate_e02a(facts, private_beta=True)
    assert result.viability == "INSUFFICIENT_INFORMATION"
    assert result.claimable_amount is None and result.calculation is None
    assert "electricity.billing.correct_amount" in result.missing_facts


def test_e02_correct_amount_can_be_added_later_by_reviewer_without_release(
    client, db, future_test_gate,
):
    case_id, _reviewer, _facts = _admit(client, db, "E02-A")
    _record_required_facts(client, case_id, [
        ("electricity.billing.billing_period", "2026-09"),
        ("electricity.billing.invoice_date", "2026-10-01"),
        ("electricity.billing.billed_amount", 120),
    ])
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    review = db.scalar(select(HumanReview).where(
        HumanReview.case_id == case_id,
        HumanReview.reason == "PRIVATE_BETA_INSUFFICIENT_INFORMATION",
    ))
    assert review is not None and review.status == "OPEN"
    completed = client.post(f"/api/admin/reviews/{review.id}/resolve-structured", json={
        "reviewer_decision": "Importe sintético revisado",
        "fact_updates": [{"key": "electricity.billing.correct_amount", "value": 80}],
    })
    assert completed.status_code == 200, completed.text
    db.expire_all()
    decision = db.get(Decision, db.get(Case, case_id).current_decision_id)
    assert decision.claimable_amount == 40
    assert db.scalar(select(Fact).where(
        Fact.case_id == case_id, Fact.key == "electricity.billing.correct_amount",
    )).created_by == "human"
    assert client.get(f"/api/cases/{case_id}").json()["decisions"] == []
    assert client.get(f"/api/cases/{case_id}/handoff").status_code == 409


def test_private_e02_rejects_bad_period_and_does_not_equate_period_to_issue_month(client, db, future_test_gate):
    case_id, _reviewer, _facts = _admit(client, db, "E02-A")
    for value in ("0000-01", "2026-00", "2026-13", "2026-9", "2026-09-01", {"month": "2026-09"}):
        assert client.post(f"/api/cases/{case_id}/facts", json={
            "key": "electricity.billing.billing_period", "value": value,
        }).status_code == 422
    _record_required_facts(client, case_id, [
        ("electricity.billing.billing_period", "2026-09"),
        ("electricity.billing.invoice_date", "2026-08-31"),
        ("electricity.billing.billed_amount", 120),
        ("electricity.billing.correct_amount", 80),
    ])
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    decision = db.get(Decision, db.get(Case, case_id).current_decision_id)
    assert decision.viability == "MEDIUM"
    assert decision.claimable_amount == 40


def test_private_c01_rejects_free_text_and_has_no_other_text_fallback(client, db, future_test_gate):
    case_id, _reviewer, _facts = _admit(client, db, "C01")
    assert "purchase.product_name" not in FIELD_SCHEMA["C01"]
    assert "purchase.defect_description" not in FIELD_SCHEMA["C01"]
    for key in ("purchase.product_name", "purchase.defect_description", "purchase.other_description"):
        assert client.post(f"/api/cases/{case_id}/facts", json={
            "key": key, "value": "narrativa sintética",
        }).status_code == 422
    for value in ("true", 1, {"answer": True}):
        assert client.post(f"/api/cases/{case_id}/facts", json={
            "key": "purchase.nonconformity_reported", "value": value,
        }).status_code == 422
    assert client.post(f"/api/cases/{case_id}/facts", json={
        "key": "purchase.nonconformity_reported", "value": None, "state": "unknown",
        "user_confirmed": False,
    }).status_code == 200
    assert client.post(f"/api/cases/{case_id}/facts", json={
        "key": "purchase.nonconformity_reported", "value": "other", "state": "unknown",
        "user_confirmed": False,
    }).status_code == 422


def test_reviewer_fact_write_cannot_restore_private_free_text(client, db, future_test_gate):
    case_id, _reviewer, _facts = _admit(client, db, "C01")
    review = HumanReview(case_id=case_id, reason="TEST_STRUCTURED_FACTS", status="OPEN")
    db.add(review)
    db.commit()
    for key, value in (
        ("purchase.product_name", "producto sintético"),
        ("purchase.defect_description", "descripción sintética"),
        ("purchase.nonconformity_reported", {"other": "texto"}),
    ):
        rejected = client.post(f"/api/admin/reviews/{review.id}/resolve-structured", json={
            "reviewer_decision": "Revisión de prueba sintética",
            "fact_updates": [{"key": key, "value": value}],
        })
        assert rejected.status_code == 422, rejected.text
        assert db.scalar(select(Fact).where(Fact.case_id == case_id, Fact.key == key)) is None
    assert db.get(HumanReview, review.id).status == "OPEN"


def test_nonparticipant_fact_write_policy_still_enforces_private_allowlist(client, db, future_test_gate):
    case_id, _reviewer, _facts = _admit(client, db, "C01")
    case = db.get(Case, case_id)
    for source in ("human", "company", "system"):
        with pytest.raises(HTTPException) as rejected:
            svc.upsert_fact(db, case, "purchase.defect_description", "narrativa sintética", created_by=source)
        assert rejected.value.status_code == 422
    with pytest.raises(HTTPException) as rejected:
        svc.upsert_fact(db, case, "purchase.price", None, state="unknown", created_by="human")
    assert rejected.value.status_code == 422
    assert db.scalar(select(Fact).where(
        Fact.case_id == case_id, Fact.key == "purchase.defect_description",
    )) is None


def test_private_c01_without_structured_allegation_is_not_classified():
    facts = {
        "purchase.buyer_is_consumer": FactValue(True),
        "purchase.seller_is_business": FactValue(True),
        "purchase.second_hand": FactValue(False),
        "purchase.nonconformity_reported": FactValue(False),
    }
    result = evaluate_c01(facts, private_beta=True)
    assert result.viability == "INSUFFICIENT_INFORMATION"
    assert result.claimable_amount is None
    assert result.rule_result == "PENDING"


def test_private_c01_price_is_progressive_and_not_required_for_triage(client, db, future_test_gate):
    case_id, _reviewer, _facts = _admit(client, db, "C01")
    preliminary = [
        ("purchase.buyer_is_consumer", True),
        ("purchase.seller_is_business", True),
        ("purchase.second_hand", False),
        ("purchase.delivery_date", "2026-08-01"),
        ("purchase.defect_manifested_date", "2026-09-01"),
        ("purchase.nonconformity_reported", True),
        ("purchase.accidental_damage_or_misuse", False),
        ("purchase.seller_denied_conformity", False),
    ]
    for key, value in preliminary:
        question = client.get(f"/api/cases/{case_id}/next-question").json()
        assert question["field"] == key
        assert question["field"] != "purchase.price"
        _record_required_facts(client, case_id, [(key, value)])
    price_question = client.get(f"/api/cases/{case_id}/next-question").json()
    assert price_question["field"] == "purchase.price"
    assert price_question["phase"] == "QUANTIFICATION" and price_question["optional"]
    assert "purchase.price" not in latest_facts(db, case_id)
    assert evaluate_c01(latest_facts(db, case_id), private_beta=True).rule_result == "APPLIES"
    assert evaluate_c01(latest_facts(db, case_id), private_beta=True).economic_value is None
    assert client.post(f"/api/cases/{case_id}/facts", json={
        "key": "purchase.price", "value": None, "state": "unknown", "user_confirmed": False,
    }).status_code == 200
    assert client.get(f"/api/cases/{case_id}/next-question").json()["done"] is True
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    decision = db.get(Decision, db.get(Case, case_id).current_decision_id)
    assert decision.viability in {"HIGH", "MEDIUM"}
    assert decision.economic_value is None


def test_global_synthetic_fields_and_26_family_manifest_are_unchanged():
    assert len(FAMILY_MANIFEST) == 26
    assert next_question({}, "C01")["field"] == "purchase.buyer_is_consumer"
    assert "purchase.product_name" in next_question({
        key: FactValue(value) for key, value in [
            ("purchase.buyer_is_consumer", True),
            ("purchase.seller_is_business", True),
            ("purchase.second_hand", False),
        ]
    }, "C01")["field"]
    assert evaluate_c01({
        "purchase.buyer_is_consumer": FactValue(True),
        "purchase.seller_is_business": FactValue(True),
        "purchase.second_hand": FactValue(False),
        "purchase.product_name": FactValue("producto sintético"),
        "purchase.delivery_date": FactValue("2026-08-01"),
        "purchase.defect_manifested_date": FactValue("2026-09-01"),
        "purchase.defect_description": FactValue("fallo sintético"),
        "purchase.accidental_damage_or_misuse": FactValue(False),
    }).rule_result == "APPLIES"
