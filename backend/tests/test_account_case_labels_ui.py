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
