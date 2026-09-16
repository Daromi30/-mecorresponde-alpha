from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_browser_refresh_reentry_uses_non_secret_hash_locator():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "case_reentry.js").read_text(encoding="utf-8")
    assert "/demo/case_reentry.js" in loader
    assert loader.rfind("/demo/case_reentry.js") > loader.rfind("/demo/case_next_step.js")
    assert "#case=" in script
    assert "restoreActiveCase()" in script
    assert "await refresh()" in script
    assert "rememberActiveCase(caseId)" in script
    assert "clearActiveCase()" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "token" not in script.lower()


def test_browser_reentry_does_not_treat_case_id_as_authorization():
    script = (STATIC / "case_reentry.js").read_text(encoding="utf-8")
    assert "/api/cases/" not in script
    assert "req(" not in script
    assert "HttpOnly" in script
    assert "authenticated account session" in script


def test_case_reentry_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "case_reentry.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
