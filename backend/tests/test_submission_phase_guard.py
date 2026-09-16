from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.calendar_clock import spain_today
from app.schemas import SubmissionInput


def test_submission_input_rejects_future_dates():
    tomorrow = spain_today() + timedelta(days=1)
    with pytest.raises(ValidationError):
        SubmissionInput(
            submitted_on=tomorrow,
            channel="email",
            reference_number="FUTURE-NOT-REAL",
        )


def test_submission_cannot_skip_diagnosis_and_prepared_action(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]

    attempted = client.post(
        f"/api/cases/{case_id}/submission",
        json={
            "submitted_on": spain_today().isoformat(),
            "channel": "email",
            "reference_number": "SHOULD-NOT-BE-RECORDED",
        },
    )
    assert attempted.status_code == 409, attempted.text

    current = client.get(f"/api/cases/{case_id}")
    assert current.status_code == 200, current.text
    body = current.json()
    assert body["status"] == "INTAKE"
    assert not any(action["type"] == "WAIT_FOR_RESPONSE" for action in body["actions"])
