from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_case_handoff_ui_is_loaded_and_javascript_parses():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "case_handoff.js").read_text(encoding="utf-8")

    assert "/demo/case_handoff.js" in loader
    assert "mcr-case-handoff" in loader
    assert "/handoff" in script
    assert "Descargar expediente estructurado" in script
    assert "logs internos" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script

    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "case_handoff.js"]:
        source = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(source)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
