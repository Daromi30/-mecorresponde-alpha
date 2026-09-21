from app.legal_source_registry import is_trusted_official_legal_url


def test_official_legal_url_policy_accepts_only_reviewed_https_hosts():
    assert is_trusted_official_legal_url("https://www.boe.es/eli/es/rd/2026/02/11/88")
    assert is_trusted_official_legal_url("https://eur-lex.europa.eu/eli/reg/2004/261/oj")

    assert not is_trusted_official_legal_url("http://eur-lex.europa.eu/eli/reg/2004/261/oj")
    assert not is_trusted_official_legal_url("https://eur-lex.europa.eu.evil.example/eli/reg/2004/261/oj")
    assert not is_trusted_official_legal_url("https://example.com/legal-text")
