from types import SimpleNamespace

from sqlalchemy import select

from app.legal_rule_governance import (
    allowed_for_case,
    professionally_approved,
    technically_executable,
)
from app.models import LegalRuleVersion
from app.services_v2 import seed_legal


def rule(status="technical_draft", reviewed_by=None):
    return SimpleNamespace(review_status=status, reviewed_by=reviewed_by)


def case(mode="SYNTHETIC"):
    return SimpleNamespace(mode=mode)


def test_new_rule_versions_default_to_technical_draft():
    assert LegalRuleVersion().review_status is None
    assert LegalRuleVersion.__table__.c.review_status.default.arg == "technical_draft"


def test_technical_draft_executes_only_with_synthetic_data():
    draft = rule()
    assert technically_executable(draft)
    assert allowed_for_case(draft, case("SYNTHETIC"))
    assert not allowed_for_case(draft, case("PRIVATE_REAL_BETA"))


def test_operational_case_release_cannot_use_or_globally_approve_a_draft():
    draft = rule()
    operationally_released_case = SimpleNamespace(
        mode="PRIVATE_REAL_BETA",
        release_approved=True,
    )
    assert not allowed_for_case(draft, operationally_released_case)
    assert draft.review_status == "technical_draft"


def test_approval_state_without_reviewer_attribution_fails_closed():
    unattributed = rule("approved")
    assert technically_executable(unattributed)
    assert not professionally_approved(unattributed)
    assert not allowed_for_case(unattributed, case("PRIVATE_REAL_BETA"))


def test_free_text_reviewer_never_proves_professional_approval():
    approved = rule("approved", "professional-review-reference")
    assert not professionally_approved(approved)
    assert not allowed_for_case(approved, case("PRIVATE_REAL_BETA"))


def test_unknown_or_future_modes_fail_closed_even_for_technical_drafts():
    draft = rule()
    for mode in (None, "", "FUTURE_MODE", "synthetic"):
        assert not allowed_for_case(draft, case(mode))


def test_unknown_or_pending_rule_state_is_never_executable():
    pending = rule("pending", "someone")
    assert not technically_executable(pending)
    assert not professionally_approved(pending)
    assert not allowed_for_case(pending, case("SYNTHETIC"))


def test_seed_demotes_legacy_approved_rule_even_with_free_text_reviewer(db):
    legacy = db.scalar(select(LegalRuleVersion).where(
        LegalRuleVersion.rule_id == "ELEC_ADDON_END_WITH_SUPPLY",
    ))
    legacy.review_status = "approved"
    legacy.reviewed_by = "arbitrary legacy text"
    db.commit()

    seed_legal(db)
    db.flush()

    assert legacy.review_status == "technical_draft"
    assert legacy.reviewed_by == "arbitrary legacy text"
    assert not professionally_approved(legacy)
