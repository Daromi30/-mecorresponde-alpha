from pathlib import Path
import shutil
import subprocess
import tempfile


ADMIN_STATIC = Path(__file__).parents[1] / "app" / "admin_static"


def test_review_context_loads_after_handoff_in_deterministic_order():
    readiness = (ADMIN_STATIC / "readiness.js").read_text(encoding="utf-8")
    handoff_pos = readiness.index("loadAdminEnhancement('case_handoff.js'")
    context_pos = readiness.index("loadAdminEnhancement('review_context.js'")
    assert handoff_pos < context_pos
    assert "script.async = false" in readiness
    assert "mcr-review-context" in readiness


def test_review_context_uses_normalized_real_dates_and_verified_outcome():
    script = (ADMIN_STATIC / "review_context.js").read_text(encoding="utf-8")
    assert "/handoff" in script
    assert "occurred_on" in script
    assert "resolved_on" in script
    assert "resolution_channel" in script
    assert "amount_recovered" in script
    assert "Los timestamps técnicos no se presentan como fecha del hecho" in script
    assert "sent_at" not in script
    assert "received_at" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_structured_review_has_no_reanalysis_opt_out():
    structured = (ADMIN_STATIC / "structured_review.js").read_text(encoding="utf-8")
    context = (ADMIN_STATIC / "review_context.js").read_text(encoding="utf-8")
    assert "reanalyzeStructuredReview" not in structured
    assert "reanalyzeStructuredReview" not in context
    assert "Reanalizar automáticamente" not in structured
    assert "reanalyze: true" in structured
    assert "Los hechos estructurados se reanalizan siempre con las reglas del Motor" in structured
    assert "input.checked = true" not in context
    assert "input.disabled = true" not in context


def test_review_context_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["readiness.js", "review_context.js", "structured_review.js"]:
        source = (ADMIN_STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(source)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
