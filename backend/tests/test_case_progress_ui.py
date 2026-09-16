from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_product_loads_resolution_progress_tracker():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "case_progress.js").read_text(encoding="utf-8")
    assert "/demo/case_progress.js" in loader
    assert "mcr-case-progress" in loader
    assert "Dónde estás" in script
    assert "Entender" in script
    assert "Comprobar" in script
    assert "Actuar" in script
    assert "Respuesta" in script
    assert "Resolver" in script


def test_progress_covers_resolution_lifecycle_without_success_probability():
    script = (STATIC / "case_progress.js").read_text(encoding="utf-8")
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
    lowered = script.lower()
    assert "probabilidad de éxito" not in lowered
    assert "porcentaje de éxito" not in lowered


def test_case_progress_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "case_progress.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
