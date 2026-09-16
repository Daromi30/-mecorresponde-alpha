from pathlib import Path
import shutil
import subprocess
import tempfile


ADMIN_STATIC = Path(__file__).parents[1] / "app" / "admin_static"


def test_backoffice_loads_structured_review_controls(client):
    response = client.get("/backoffice/")
    assert response.status_code == 200
    assert "structured_review.js" in response.text


def test_structured_review_ui_reanalyzes_facts_without_manual_legal_fields():
    script = (ADMIN_STATIC / "structured_review.js").read_text(encoding="utf-8")
    assert "/resolve-structured" in script
    assert "fact_updates" in script
    assert "reanalyze" in script
    assert "Guardar hechos y reanalizar" in script
    assert "RESERVED_PREFIXES" in script
    for prefix in ["system.", "legal.", "rule.", "decision.", "action."]:
        assert prefix in script
    assert "legal_basis" not in script
    assert "success_probability" not in script


def test_backoffice_hides_legacy_generic_review_completion_path():
    html = (ADMIN_STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="reviewResolutionAnchor" style="display:none"' in html
    assert 'id="completeReview" type="button" disabled hidden' in html
    assert "/api/admin/reviews/' + reviewId + '/complete" not in html
    assert "Completar revisión" not in html


def test_structured_review_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (ADMIN_STATIC / "structured_review.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
