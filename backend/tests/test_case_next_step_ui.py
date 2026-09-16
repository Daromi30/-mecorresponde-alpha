from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_product_loads_status_aware_next_step_guidance():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    assert "/demo/case_next_step.js" in loader
    assert "mcr-case-next-step" in loader
    assert "Qué hago ahora" in script
    assert "Completa el dato que falta" in script
    assert "Prepara la acción con este diagnóstico" in script
    assert "Añade la respuesta cuando llegue" in script
    assert "Comprueba que la empresa haya cumplido" in script


def test_next_step_guidance_covers_every_user_facing_lifecycle_state():
    script = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    for status in [
        "INTAKE",
        "NEEDS_INFORMATION",
        "DIAGNOSED",
        "READY_TO_SUBMIT",
        "WAITING_RESPONSE",
        "RESPONSE_RECEIVED",
        "HUMAN_REVIEW",
        "REANALYZING",
        "RESOLVED_PENDING_EXECUTION",
        "RESOLVED",
        "CLOSED_UNSUPPORTED",
    ]:
        assert status in script
    assert "prepareClaim()" in script
    assert "responseCard" in script
    assert "outcomeCard" in script
    assert "organismo" not in script.lower()
    assert "probabilidad" not in script.lower()


def test_case_next_step_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
