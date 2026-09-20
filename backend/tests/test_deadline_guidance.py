from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_product_enhancement_loads_verified_deadline_guidance_before_submission_form():
    quality = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    assert "/demo/deadline_guidance.js" in quality
    assert "mcr-deadline-guidance" in quality
    assert "/demo/browser_clock.js" in quality
    assert quality.index("/demo/browser_clock.js") < quality.index("/demo/deadline_guidance.js")
    assert quality.index("/demo/deadline_guidance.js") < quality.index("/demo/submission_evidence.js")


def test_deadline_guidance_only_formats_verified_submission_guidance():
    script = (STATIC / "deadline_guidance.js").read_text(encoding="utf-8")
    assert "window.mcrSubmissionGuidance = submissionGuidance" in script
    assert "legal_response_period_business_days" in script
    assert "LEGAL_PERIOD_ONLY" in script
    assert "NOT_CONFIGURED" in script
    assert "No calculo una fecha exacta" in script
    assert "No aplico un plazo sectorial" in script
    assert "official_url" in script
    assert "Fecha orientativa" not in script
    assert "PROVISIONAL_CALENDAR" not in script
    assert "registerSubmission" not in script
    assert "submissionEvidencePanel" not in script
    assert "submissionDate" not in script


def test_submission_form_uses_shared_verified_guidance_without_a_second_panel():
    script = (STATIC / "submission_evidence.js").read_text(encoding="utf-8")
    assert "submissionEvidenceFields" in script
    assert "submissionSentOn" in script
    assert "submissionChannel" in script
    assert "submissionReference" in script
    assert "MECORRESPONDE no rellenará esos datos por ti" in script
    assert "mcrSpainDateIso()" in script
    assert "mcrSubmissionGuidance(submission)" in script
    assert "Fecha orientativa calculada" not in script


def test_submission_ui_modules_parse_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["deadline_guidance.js", "submission_evidence.js"]:
        script = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
