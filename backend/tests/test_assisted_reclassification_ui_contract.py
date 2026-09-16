from pathlib import Path


ADMIN_STATIC = Path(__file__).parents[1] / "app" / "admin_static"


def test_assisted_routing_ui_only_appears_for_unsupported_classification_reviews():
    script = (ADMIN_STATIC / "structured_review.js").read_text(encoding="utf-8")
    assert "review?.reason !== 'UNSUPPORTED_CLASSIFICATION'" in script
    assert "completeSection.style.display = 'none'" in script
    assert "Reclasificar al Motor" in script
    assert "Reclasificar y continuar el intake" in script
    assert "El Motor vuelve al intake" in script
