from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_escalation_guard_is_loaded_and_blocks_repeated_initial_action_ui():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "escalation_guard.js").read_text(encoding="utf-8")

    assert "/demo/escalation_guard.js" in loader
    assert "POST_RESPONSE_ESCALATION" in script
    assert "POST_DENIAL_ESCALATION_REVIEW" not in script
    assert "No voy a repetir la reclamación inicial" in script
    assert "inventar un organismo, plazo o vía jurídica" in script
    assert "prepareClaim()" not in script


def test_escalation_guard_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "escalation_guard.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
