from pathlib import Path


DOC = Path(__file__).parents[2] / "docs" / "internal-beta-runbook.md"


def test_internal_beta_runbook_preserves_synthetic_only_boundary():
    text = DOC.read_text(encoding="utf-8")
    assert "NO usar datos personales" in text
    assert "/health/persistence" in text
    assert "BETA_BLOCKER" in text
    assert "C01, C02, C03, C04, C05" in text
    assert "E01, E02-A, E02-B, E03, E04-A, E04-B, E05, E06, E07" in text
    assert "P0" in text and "P1" in text
    assert "datos reales sigue prohibido" in text
