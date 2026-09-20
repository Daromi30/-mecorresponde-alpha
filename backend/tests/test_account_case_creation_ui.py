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


def test_post_login_session_loss_cannot_fall_through_to_saved_case_success():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    block = html[html.index("async function submitAccount(event){"):html.index("async function logoutAccount()")]

    load_cases = block.index("await loadMyCases();")
    session_guard = block.index("if(!currentUser){", load_cases)
    expired_copy = block.index("La sesión ha caducado justo después de iniciar sesión", session_guard)
    early_return = block.index("return;", expired_copy)
    close_account = block.index("closeAccount();", early_return)
    success_copy = block.index("Expediente guardado en tu cuenta.", close_account)

    assert load_cases < session_guard < expired_copy < early_return < close_account < success_copy


def test_created_case_session_expiry_does_not_offer_dead_retry_button():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    start = html.index("async function createCase(){")
    end = html.index("async function refresh(){", start)
    block = html[start:end]

    load_cases = block.index("if(currentUser)await loadMyCases();")
    claim_error = block.index("if(accountClaimError)", load_cases)
    signed_in_retry = block.index("if(currentUser){message(", claim_error)
    expired_copy = block.index("tu sesión ha caducado. Vuelve a iniciar sesión", signed_in_retry)

    assert load_cases < claim_error < signed_in_retry < expired_copy
    assert "retryCaseClaimBtn" in block[signed_in_retry:expired_copy]
    assert "retryCaseClaimBtn" not in block[expired_copy:]


def test_retry_case_claim_prompts_login_when_session_has_expired():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    start = html.index("async function retryClaimCurrentCase(){")
    end = html.index("async function createCase(){", start)
    block = html[start:end]

    assert "if(!caseId)return;" in block
    assert "if(!currentUser){openAccount('login');" in block
    assert "Tu sesión ha caducado. Vuelve a entrar para guardar este expediente." in block
    assert "if(!currentUser||!caseId)return;" not in block
