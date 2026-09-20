from pathlib import Path


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_frontend_has_no_legacy_case_mutation_fallbacks():
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in [STATIC / "index.html", *sorted(STATIC.glob("*.js"))]
    }

    forbidden = [
        "`/api/cases/${caseId}/responses`",
        "`/api/cases/${caseId}/outcome`",
        "submitted_on:new Date().toISOString().slice(0,10)",
        "channel:'user_confirmed'",
    ]
    for filename, source in sources.items():
        for token in forbidden:
            assert token not in source, f"{filename} reintroduced unsafe browser fallback: {token}"

    html = sources["index.html"]
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
