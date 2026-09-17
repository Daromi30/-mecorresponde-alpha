from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_monitor_followup_loads_after_base_next_step_and_before_reentry():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    base = loader.index("/demo/case_next_step.js")
    monitor = loader.index("/demo/monitor_followup.js")
    reentry = loader.index("/demo/case_reentry.js")
    assert base < monitor < reentry
    assert "mcr-monitor-followup" in loader


def test_monitor_followup_card_routes_back_to_guided_question_area():
    script = (STATIC / "monitor_followup.js").read_text(encoding="utf-8")
    assert "startsWith('MONITOR_')" in script
    assert "Actualizar si ha cambiado" in script
    assert "questionArea" in script
    assert "const baseRefresh = refresh" in script


def test_monitor_followup_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    source = (STATIC / "monitor_followup.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(source)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
