from pathlib import Path


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_created_case_survives_account_claim_failure_in_browser_flow():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert "let accountClaimError=null" in html
    assert "catch(e){accountClaimError=e}" in html
    assert "$('workspace').classList.remove('hidden')" in html
    assert "await refresh()" in html
    assert "if(accountClaimError){message(`El expediente se ha creado y sigue disponible en este navegador" in html
    assert "pero no se ha podido guardar en tu cuenta" in html
    assert "async function retryClaimCurrentCase()" in html
    assert "id=\"retryCaseClaimBtn\"" in html
    assert 'onclick="retryClaimCurrentCase()"' in html
    assert "await req(`/api/cases/${caseId}/claim`,{method:'POST'})" in html
    assert "setBusy(btn,true,'Guardando…')" in html

    claim_failure = html.index("catch(e){accountClaimError=e}")
    workspace_open = html.index("$('workspace').classList.remove('hidden')", claim_failure)
    refresh = html.index("await refresh()", workspace_open)
    warning = html.index("if(accountClaimError){message(", refresh)
    assert claim_failure < workspace_open < refresh < warning
