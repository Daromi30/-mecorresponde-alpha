from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_evidence_forms_share_spain_civil_calendar_clock():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    assert "/demo/browser_clock.js" in loader
    assert loader.index("/demo/browser_clock.js") < loader.index("/demo/submission_evidence.js")
    assert loader.index("/demo/browser_clock.js") < loader.index("/demo/response_evidence.js")
    assert loader.index("/demo/browser_clock.js") < loader.index("/demo/outcome_evidence.js")

    clock = (STATIC / "browser_clock.js").read_text(encoding="utf-8")
    assert "Europe/Madrid" in clock
    assert "formatToParts" in clock
    assert "window.mcrSpainDateIso" in clock

    for filename in ["submission_evidence.js", "response_evidence.js", "outcome_evidence.js"]:
        source = (STATIC / filename).read_text(encoding="utf-8")
        assert "mcrSpainDateIso()" in source
        assert "localTodayIso" not in source


def test_spain_browser_clock_handles_midnight_boundaries_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return

    source = (STATIC / "browser_clock.js").read_text(encoding="utf-8")
    harness = (
        "global.window = global;\n"
        + source
        + "\n"
        + "console.log(mcrSpainDateIso(new Date('2026-09-19T22:30:00Z')));\n"
        + "console.log(mcrSpainDateIso(new Date('2026-01-01T23:30:00Z')));\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(harness)
        path = handle.name

    result = subprocess.run([node, path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["2026-09-20", "2026-01-02"]
