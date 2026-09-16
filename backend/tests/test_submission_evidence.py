import pytest
from pydantic import ValidationError

from app.schemas import SubmissionInput


def test_submission_input_accepts_traceable_channel_and_reference():
    payload = SubmissionInput(
        submitted_on="2026-09-15",
        channel="web_form",
        reference_number="RE-2026-12345",
    )
    assert payload.submitted_on.isoformat() == "2026-09-15"
    assert payload.channel == "web_form"
    assert payload.reference_number == "RE-2026-12345"


def test_submission_channel_and_reference_are_bounded_to_persistence_limits():
    with pytest.raises(ValidationError):
        SubmissionInput(
            submitted_on="2026-09-15",
            channel="x" * 31,
            reference_number=None,
        )

    with pytest.raises(ValidationError):
        SubmissionInput(
            submitted_on="2026-09-15",
            channel="email",
            reference_number="x" * 101,
        )


def test_submission_reference_remains_optional():
    payload = SubmissionInput(submitted_on="2026-09-15", channel="phone")
    assert payload.reference_number is None