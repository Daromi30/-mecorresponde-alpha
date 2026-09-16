from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_claimant_ui_distinguishes_post_response_and_professional_review_states():
    script = (STATIC / "escalation_guard.js").read_text(encoding="utf-8")
    assert "POST_RESPONSE_ESCALATION" in script
    assert "PROFESSIONAL_REVIEW" in script
    assert "El expediente está en revisión profesional" in script
    assert "requiere criterio jurídico humano" in script
    assert "probabilidad de éxito" in script
    assert "repetir la reclamación inicial" in script


def test_escalation_guard_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "escalation_guard.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
