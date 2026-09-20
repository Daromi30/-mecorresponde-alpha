import pytest

from app import services_v2
from app.family_manifest import FAMILY_MANIFEST


@pytest.mark.parametrize("family_code", tuple(FAMILY_MANIFEST))
def test_create_case_uses_registered_family_title(db, monkeypatch, family_code):
    entry = FAMILY_MANIFEST[family_code]

    monkeypatch.setattr(
        services_v2.gateway,
        "classify",
        lambda _message: {
            "vertical": entry.vertical,
            "family": family_code,
            "confidence": 1.0,
        },
    )

    case = services_v2.create_case(db, "synthetic intake")

    assert case.family == family_code
    assert case.vertical == entry.vertical
    assert case.title == entry.title
    assert case.status == "INTAKE"


def test_create_case_keeps_unclassified_fallback_title(db, monkeypatch):
    monkeypatch.setattr(
        services_v2.gateway,
        "classify",
        lambda _message: {
            "vertical": None,
            "family": None,
            "confidence": 0.0,
        },
    )

    case = services_v2.create_case(db, "unsupported synthetic intake")

    assert case.title == "Caso para revisión asistida"
    assert case.status == "HUMAN_REVIEW"
