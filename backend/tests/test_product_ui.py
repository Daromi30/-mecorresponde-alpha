from pathlib import Path
import shutil
import subprocess
import tempfile


def _ui() -> str:
    return (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")


def test_consumer_ui_explains_value_without_internal_jargon():
    html = _ui()
    assert "Cuéntame qué te ha pasado" in html
    assert "¿Me corresponde?" in html
    assert "¿Cuánto hay en juego?" in html
    assert "¿Qué hago ahora?" in html
    assert "Internal Alpha" not in html
    assert "vertical slice" not in html.lower()
    assert "E04-B" not in html


def test_consumer_ui_supports_generic_multifamily_intake():
    html = _ui()
    for input_type in ["boolean_unknown", "choice", "money", "number", "date", "charges"]:
        assert input_type in html
    assert "/api/cases/${caseId}/next-question" in html
    assert "/api/cases/${caseId}/diagnose" in html
    assert "/api/cases/${caseId}/prepare-claim" in html

    static = Path(__file__).parents[1] / "app" / "static"
    response = (static / "response_evidence.js").read_text(encoding="utf-8")
    outcome = (static / "outcome_evidence.js").read_text(encoding="utf-8")
    assert "/api/cases/${caseId}/responses/evidenced" in response
    assert "/api/cases/${caseId}/outcome/evidenced" in outcome
    assert "`/api/cases/${caseId}/responses`" not in html
    assert "`/api/cases/${caseId}/outcome`" not in html


def test_consumer_ui_keeps_accounts_optional_and_can_recover_cases():
    html = _ui()
    assert "No necesitas registrarte para empezar" in html
    assert "Guardar este expediente" in html
    assert "Mis expedientes" in html
    assert "/api/auth/me" in html
    assert "/api/auth/${accountMode}" in html
    assert "/api/auth/cases" in html
    assert "/api/cases/${caseId}/claim" in html
    assert "localStorage" not in html
    assert "sessionStorage" not in html
    assert "todavía no hay recuperación de contraseña por email" in html


def test_consumer_ui_keeps_official_legal_sources_visible():
    html = _ui()
    assert "Fuentes jurídicas verificables" in html
    assert "official_url" in html
    assert "Abrir fuente oficial" in html


def test_consumer_ui_does_not_claim_unsupported_document_upload():
    html = _ui()
    assert "Subir factura" not in html
    assert "type=\"file\"" not in html


def test_worth_pursuing_codes_have_readable_fail_closed_labels():
    html = _ui()
    for code in [
        "YES_IF_LOW_COST", "NEEDS_INFORMATION", "NEEDS_REANALYSIS",
        "NO_PAID_MANAGEMENT", "PROFESSIONAL_REVIEW", "NO_FURTHER_ACTION", "WAIT",
    ]:
        assert f"{code}:'" in html
    assert "[v]||'Pendiente de revisión'" in html


def test_consumer_ui_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    html = _ui()
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
