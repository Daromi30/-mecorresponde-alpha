from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_saved_case_list_uses_user_facing_area_labels_not_family_codes():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "account_case_labels.js").read_text(encoding="utf-8")
    assert "/demo/account_case_labels.js" in loader
    assert "Luz y electricidad" in script
    assert "Compras y garantías" in script
    assert "Telecomunicaciones" in script
    assert "caseItem.family" not in script
    assert "c.family" not in script
    assert "humanStatus(caseItem.status)" in script

    # The base HTML must also fail closed: the enhancement may load a moment later or fail.
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    load_cases = html[html.index("async function loadMyCases"):html.index("async function openOwnedCase")]
    assert "c.family" not in load_cases
    assert "family" not in load_cases


def test_saved_case_label_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "account_case_labels.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_account_case_list_clears_stale_signed_in_state_on_401():
    script = (STATIC / "account_case_labels.js").read_text(encoding="utf-8")

    assert "if (error?.status === 401)" in script
    assert "currentUser = null;" in script
    assert "setAccountMode('login');" in script
    assert "renderAccountState();" in script
    assert "Tu sesión ha caducado. Vuelve a entrar para ver tus expedientes." in script

    status = script.index("if (error?.status === 401)")
    clear_user = script.index("currentUser = null;", status)
    render = script.index("renderAccountState();", clear_user)
    assert status < clear_user < render
