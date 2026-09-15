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


def test_structured_review_ui_keeps_free_text_path_as_non_structured_fallback():
    script = (ADMIN_STATIC / "structured_review.js").read_text(encoding="utf-8")
    assert "Cerrar revisión solo con una nota interna" in script
    assert "no añade hechos estructurados" in script


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
