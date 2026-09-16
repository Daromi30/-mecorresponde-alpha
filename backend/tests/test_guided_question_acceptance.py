from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile


# Reuse the single beta scenario catalogue without maintaining a second copy of
# 14 legal test fixtures. Loading by path keeps this independent of whether the
# tests directory is installed as a Python package.
_matrix_path = Path(__file__).with_name("test_beta_acceptance_matrix.py")
_spec = importlib.util.spec_from_file_location("mcr_beta_acceptance_matrix", _matrix_path)
assert _spec and _spec.loader
_matrix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_matrix)
SCENARIOS = _matrix.SCENARIOS
STATIC = Path(__file__).parents[1] / "app" / "static"

_UI_EXACT_INPUT_TYPES = {
    "text",
    "boolean",
    "boolean_unknown",
    "money",
    "number",
    "integer",
    "date",
    "date_optional",
    "charges",
    "choice",
}


def _ui_supports_input_type(input_type: str | None) -> bool:
    value = input_type or "text"
    return value in _UI_EXACT_INPUT_TYPES or value.startswith("choice:")


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
    seen_input_types = set()
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
            input_type = q.get("input_type")
            seen_input_types.add(input_type)
            assert _ui_supports_input_type(input_type), (
                f"{family}: the Motor emitted input_type={input_type!r}, but the product UI "
                "has no declared safe renderer for it"
            )
            assert field, (family, q)
            assert field not in answered, f"{family}: guided intake repeated {field}"

            if input_type == "charges":
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

    # Protect the input types that were previously silently rendered as free text.
    assert "integer" in seen_input_types
    assert "date_optional" in seen_input_types
    assert any(str(value).startswith("choice:") for value in seen_input_types)


def test_guided_question_ui_contract_is_loaded_and_javascript_parses():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "guided_question_inputs.js").read_text(encoding="utf-8")

    assert "/demo/guided_question_inputs.js" in loader
    assert "mcr-guided-question-inputs" in loader
    assert "type.startsWith('choice:')" in script
    assert "type === 'integer'" in script
    assert "type === 'date_optional'" in script
    assert "Number.isInteger" in script
    assert "No voy a pedirte un dato con un formato" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script

    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "guided_question_inputs.js"]:
        source = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(source)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
