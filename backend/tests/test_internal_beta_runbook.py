from pathlib import Path
import re

from app.family_manifest import supported_family_codes


DOC = Path(__file__).parents[2] / "docs" / "internal-beta-runbook.md"


def test_internal_beta_runbook_preserves_synthetic_only_boundary():
    text = DOC.read_text(encoding="utf-8")
    assert "NO usar datos personales" in text
    assert "/health/persistence" in text
    assert "BETA_BLOCKER" in text
    matrix = text.split("## Matriz de familias", 1)[1].split("## Severidad de defectos", 1)[0]
    documented_codes = set(re.findall(r"\b(?:E\d{2}-[AB]|[A-Z]\d{2})\b", matrix))
    assert documented_codes == set(supported_family_codes())
    assert "14 familias" not in text
    assert "RESOLVED_PENDING_EXECUTION" in text and "VERIFY_EXECUTION" in text
    assert "P0" in text and "P1" in text
    assert "datos reales sigue prohibido" in text
