from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_product_enhancement_loads_verified_deadline_guidance():
    quality = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    assert "/demo/deadline_guidance.js" in quality
    assert "mcr-deadline-guidance" in quality


def test_deadline_guidance_shows_verified_period_but_not_synthetic_date():
    script = (STATIC / "deadline_guidance.js").read_text(encoding="utf-8")
    assert "legal_response_period_business_days" in script
    assert "LEGAL_PERIOD_ONLY" in script
    assert "No calculo una fecha exacta" in script
    assert "official_url" in script
    assert "Fecha orientativa" not in script
    assert "PROVISIONAL_CALENDAR" not in script


def test_deadline_guidance_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "deadline_guidance.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
