from __future__ import annotations

import importlib.util
from pathlib import Path


# Reuse the single beta scenario catalogue without maintaining a second copy of
# 14 legal test fixtures. Loading by path keeps this independent of whether the
# tests directory is installed as a Python package.
_matrix_path = Path(__file__).with_name("test_beta_acceptance_matrix.py")
_spec = importlib.util.spec_from_file_location("mcr_beta_acceptance_matrix", _matrix_path)
assert _spec and _spec.loader
_matrix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_matrix)
SCENARIOS = _matrix.SCENARIOS


def _answer_fact(client, case_id: str, field: str, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": field,
            "value": value,
            "state": "confirmed",
            "user_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text


def test_every_beta_family_can_be_completed_using_only_the_guided_question_contract(client):
    for family, scenario in SCENARIOS.items():
        created = client.post("/api/cases", json={"message": scenario["message"]})
        assert created.status_code == 200, f"{family}: {created.text}"
        body = created.json()
        assert body["family"] == family
        case_id = body["id"]

        answered = set()
        charges_recorded = False
        for _ in range(40):
            question = client.get(f"/api/cases/{case_id}/next-question")
            assert question.status_code == 200, f"{family}: {question.text}"
            q = question.json()
            if q.get("done"):
                break

            field = q.get("field")
            assert field, (family, q)
            assert field not in answered, f"{family}: guided intake repeated {field}"

            if q.get("input_type") == "charges":
                charges = scenario.get("charges")
                assert charges, f"{family}: question flow requests charges absent from beta fixture"
                response = client.post(
                    f"/api/cases/{case_id}/charges",
                    json={"charges": charges},
                )
                assert response.status_code == 200, f"{family}: {response.text}"
                charges_recorded = True
            else:
                assert field in scenario["facts"], (
                    f"{family}: guided intake requested {field}, but the accepted beta "
                    "scenario has no answer for it"
                )
                _answer_fact(client, case_id, field, scenario["facts"][field])
            answered.add(field)
        else:
            raise AssertionError(f"{family}: guided intake did not terminate within 40 questions")

        if scenario.get("charges"):
            assert charges_recorded, f"{family}: expected charge evidence was never requested"

        diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
        assert diagnosis.status_code == 200, f"{family}: {diagnosis.text}"
        assert diagnosis.json()["viability"] == "HIGH", f"{family}: {diagnosis.json()}"

        prepared = client.post(f"/api/cases/{case_id}/prepare-claim")
        assert prepared.status_code == 200, f"{family}: {prepared.text}"
        assert prepared.json()["legal_basis"], family
