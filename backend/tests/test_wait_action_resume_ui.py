from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_wait_next_step_uses_protected_resume_endpoint():
    script = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    assert "async function resumeWaitAction()" in script
    assert "/resume-wait" in script
    assert "Comprobar de nuevo" in script
    assert "if (type.startsWith('WAIT_'))" in script
    assert "action: () => resumeWaitAction()" in script


def test_wait_resume_ui_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    source = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(source)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
