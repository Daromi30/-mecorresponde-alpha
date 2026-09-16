from pathlib import Path


ADMIN_STATIC = Path(__file__).parents[1] / "app" / "admin_static"


def test_backoffice_exposes_professional_handoff_only_for_escalation_reasons():
    script = (ADMIN_STATIC / "structured_review.js").read_text(encoding="utf-8")
    assert "POST_DENIAL_ESCALATION_REVIEW" in script
    assert "PROFESSIONAL_ESCALATION_REQUIRED" in script
    assert "/escalate-professional" in script
    assert "Escalar a revisión profesional" in script
    assert "Cargar dossier para handoff" in script
    assert "/handoff" in script
    assert "no selecciona organismo, vía, plazo, remedio ni probabilidad de éxito" in script
    assert "completeSection.style.display = 'none'" in script
