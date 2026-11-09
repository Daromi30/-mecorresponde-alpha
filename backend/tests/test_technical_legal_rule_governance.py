from types import SimpleNamespace

from app.legal_rule_governance import (
    allowed_for_case,
    professionally_approved,
    technically_executable,
)
from app.models import LegalRuleVersion


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


def test_case_level_professional_release_can_use_draft_for_that_case_only():
    draft = rule()
    assert allowed_for_case(
        draft,
        case("PRIVATE_REAL_BETA"),
        case_release_approved=True,
    )


def test_approval_state_without_reviewer_attribution_fails_closed():
    unattributed = rule("approved")
    assert technically_executable(unattributed)
    assert not professionally_approved(unattributed)
    assert not allowed_for_case(unattributed, case("PRIVATE_REAL_BETA"))


def test_attributed_professional_approval_allows_real_case_rule():
    approved = rule("approved", "professional-review-reference")
    assert professionally_approved(approved)
    assert allowed_for_case(approved, case("PRIVATE_REAL_BETA"))


def test_unknown_or_pending_rule_state_is_never_executable():
    pending = rule("pending", "someone")
    assert not technically_executable(pending)
    assert not professionally_approved(pending)
    assert not allowed_for_case(pending, case("SYNTHETIC"))
