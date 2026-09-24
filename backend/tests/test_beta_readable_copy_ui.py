from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_claimant_diagnosis_hides_internal_codes_but_keeps_history_explicit():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    render = html.split("function renderDecision(d)", 1)[1].split("function renderFullDiagnosis", 1)[0]

    assert "OUT_OF_SCOPE:'Fuera del alcance automatizado'" in html
    assert "PRICE_REDUCTION_REQUIRES_PROPORTIONAL_VALUATION:'La rebaja del precio requiere valorar la proporción'" in html
    assert "counterargumentLabel(x.type)" in render
    assert "counterargumentStatusLabel(x.status)" in render
    assert "ruleResultLabel(r.result)" in render
    assert "r.rule_id" not in render
    assert "Diagnóstico previo · consulta el estado actual" in render
    assert "Importe calculado en el diagnóstico previo" in render
    assert "other_urban_use:'Otro uso urbano'" in html
    assert "tourist_or_hospitality:'Alquiler turístico u hospedaje'" in html
    assert "escapeHtml(choiceLabel(o))" in html


def test_claimant_inline_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
