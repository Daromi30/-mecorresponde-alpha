from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_product_enhancement_loads_verified_deadline_guidance():
    quality = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    assert "/demo/deadline_guidance.js" in quality
    assert "mcr-deadline-guidance" in quality
    assert "/demo/browser_clock.js" in quality
    assert quality.index("/demo/browser_clock.js") < quality.index("/demo/deadline_guidance.js")


def test_submission_registration_requires_real_date_channel_and_optional_reference():
    script = (STATIC / "deadline_guidance.js").read_text(encoding="utf-8")
    assert "submissionEvidencePanel" in script
    assert "submissionDate" in script
    assert "submissionChannel" in script
    assert "submissionReference" in script
    assert "No asumimos que haya sido hoy" in script
    assert "submitted_on: date" in script
    assert "channel," in script
    assert "reference_number: reference || null" in script
    assert "dateInput.max = mcrSpainDateIso()" in script
    assert "localTodayIso" not in script
    assert "channel: 'user_confirmed'" not in script
    assert "reference_number: null" not in script


def test_deadline_guidance_shows_verified_period_but_not_synthetic_date():
    script = (STATIC / "deadline_guidance.js").read_text(encoding="utf-8")
    assert "legal_response_period_business_days" in script
    assert "LEGAL_PERIOD_ONLY" in script
    assert "NOT_CONFIGURED" in script
    assert "No calculo una fecha exacta" in script
    assert "No aplico un plazo sectorial" in script
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