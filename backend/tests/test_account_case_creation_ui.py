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


def test_successful_login_survives_optional_current_case_claim_failure():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    block = html[html.index("async function submitAccount(event){"):html.index("async function logoutAccount()")]

    assert "Authentication and saving the currently open case are separate operations." in block
    assert "currentUser=data.user;" in block
    assert "renderAccountState();" in block
    assert "let accountClaimError=null;" in block
    assert "accountClaimError=e;" in block
    assert "Sesión iniciada. El expediente sigue disponible en este navegador" in block
    assert 'id="retryCaseClaimBtn"' in block
    assert 'onclick="retryClaimCurrentCase()"' in block

    signed_in = block.index("currentUser=data.user;")
    render = block.index("renderAccountState();", signed_in)
    claim = block.index("await req(`/api/cases/${caseId}/claim`", render)
    capture_claim_error = block.index("accountClaimError=e;", claim)
    warning = block.index("if(accountClaimError)", capture_claim_error)
    assert signed_in < render < claim < capture_claim_error < warning

    # A downstream case-save/refresh error must not be rendered as a login failure.
    auth_error = block.index("$('accountError').innerHTML")
    assert auth_error < signed_in
