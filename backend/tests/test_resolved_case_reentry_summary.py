from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_resolved_case_summary_is_loaded_after_handoff_module():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    assert "/demo/case_handoff.js" in loader
    assert "/demo/resolved_case_summary.js" in loader
    assert loader.index("/demo/case_handoff.js") < loader.index("/demo/resolved_case_summary.js")


def test_resolved_case_reentry_restores_verified_outcome_details():
    script = (STATIC / "resolved_case_summary.js").read_text(encoding="utf-8")
    assert "caseData?.status !== 'RESOLVED'" in script
    assert "/handoff" in script
    assert "verified_by_user" in script
    assert "amount_recovered" in script
    assert "resolution_channel" in script
    assert "resolved_on" in script
    assert "non_monetary_result" in script
    assert "Fecha real de cumplimiento" in script
    assert "No consta una fecha exacta" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_resolved_case_summary_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "resolved_case_summary.js"]:
        source = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(source)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
