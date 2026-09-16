from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_timeline_prefers_real_communication_dates_without_inventing_response_mapping():
    script = (STATIC / "case_timeline.js").read_text(encoding="utf-8")
    assert "/communications" in script
    assert "CLAIM_SUBMITTED" in script
    assert "CLAIM_ACCEPTED_PENDING_EXECUTION" in script
    assert "occurred_on" in script
    assert "inboundDates.length === 1" in script
    assert "event.resolved_on" in script
    assert "eventTimeCopy(event, communications)" in script
    assert "Timeline remains usable with technical record times" in script


def test_timeline_real_date_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    source = (STATIC / "case_timeline.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(source)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
