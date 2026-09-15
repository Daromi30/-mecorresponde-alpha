from pathlib import Path
import shutil
import subprocess
import tempfile


def _ui() -> str:
    return (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")


def test_consumer_ui_explains_value_without_internal_jargon():
    html = _ui()
    assert "Cuéntame qué te ha pasado" in html
    assert "¿Me corresponde?" in html
    assert "¿Cuánto hay en juego?" in html
    assert "¿Qué hago ahora?" in html
    assert "Internal Alpha" not in html
    assert "vertical slice" not in html.lower()
    assert "E04-B" not in html


def test_consumer_ui_supports_generic_multifamily_intake():
    html = _ui()
    for input_type in ["boolean_unknown", "choice", "money", "number", "date", "charges"]:
        assert input_type in html
    assert "/api/cases/${caseId}/next-question" in html
    assert "/api/cases/${caseId}/diagnose" in html
    assert "/api/cases/${caseId}/prepare-claim" in html
    assert "/api/cases/${caseId}/responses" in html
    assert "/api/cases/${caseId}/outcome" in html


def test_consumer_ui_does_not_claim_unsupported_document_upload():
    html = _ui()
    assert "Subir factura" not in html
    assert "type=\"file\"" not in html


def test_consumer_ui_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    html = _ui()
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
