from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_submission_ui_requires_real_date_channel_and_uses_existing_evidence_api():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "submission_evidence.js").read_text(encoding="utf-8")

    assert "/demo/submission_evidence.js" in loader
    assert "mcr-submission-evidence" in loader
    assert "submissionSentOn" in script
    assert "submissionChannel" in script
    assert "submissionReference" in script
    assert "MECORRESPONDE no rellenará esos datos por ti" in script
    assert "La fecha de envío no puede estar en el futuro" in script
    assert "Selecciona el canal de envío" in script
    assert "/api/cases/${caseId}/submission" in script
    assert "submitted_on: sentOn" in script
    assert "channel," in script
    assert "reference_number: reference || null" in script
    assert "channel:'user_confirmed'" not in script
    assert "new Date().toISOString().slice(0,10),channel" not in script


def test_enhancement_loader_preserves_wrapper_order_instead_of_async_racing():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    assert "script.async = false" in loader
    assert loader.index("/demo/submission_evidence.js") < loader.index("/demo/response_evidence.js")
    assert loader.index("/demo/escalation_guard.js") < loader.index("/demo/case_next_step.js")


def test_submission_evidence_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "submission_evidence.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
