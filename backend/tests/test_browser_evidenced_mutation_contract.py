from pathlib import Path


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_base_html_has_no_legacy_case_mutation_fallbacks():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert "`/api/cases/${caseId}/responses`" not in html
    assert "`/api/cases/${caseId}/outcome`" not in html
    assert "submitted_on:new Date().toISOString().slice(0,10)" not in html
    assert "channel:'user_confirmed'" not in html

    assert "evidenceModuleUnavailable" in html
    assert "no se ha registrado ningún cambio" in html


def test_evidence_modules_are_the_only_browser_mutation_implementations():
    submission = (STATIC / "submission_evidence.js").read_text(encoding="utf-8")
    response = (STATIC / "response_evidence.js").read_text(encoding="utf-8")
    outcome = (STATIC / "outcome_evidence.js").read_text(encoding="utf-8")

    assert "/submission" in submission
    assert "/responses/evidenced" in response
    assert "/outcome/evidenced" in outcome

    assert "mcrSpainDateIso()" in submission
    assert "mcrSpainDateIso()" in response
    assert "mcrSpainDateIso()" in outcome
