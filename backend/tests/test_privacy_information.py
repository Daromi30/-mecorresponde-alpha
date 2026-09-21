from types import SimpleNamespace

from app.config import settings
from app.privacy_information import privacy_information_status, render_full_privacy_page


def _complete_settings(**overrides):
    values = {
        "privacy_information_reviewed": True,
        "privacy_controller_identity": "Responsable real",
        "privacy_controller_contact": "contacto real",
        "privacy_dpo_applicability_confirmed": True,
        "privacy_dpo_required": False,
        "privacy_dpo_contact": "",
        "privacy_purposes": "Finalidades reales",
        "privacy_legal_basis": "Base jurídica real",
        "privacy_retention": "Conservación real",
        "privacy_recipients": "Destinatarios reales",
        "privacy_international_transfers": "Transferencias reales",
        "privacy_rights": "Derechos reales",
        "privacy_automated_decisions": "Decisiones reales",
        "privacy_special_categories": "Categorías reales",
        "privacy_data_requirement": "Necesidad real",
        "privacy_notice_version": "v1",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_privacy_information_fails_closed_when_incomplete_or_unreviewed():
    incomplete = _complete_settings(privacy_controller_identity="")
    assert privacy_information_status(incomplete).ready is False
    assert "privacy_controller_identity" in privacy_information_status(incomplete).missing_fields

    unreviewed = _complete_settings(privacy_information_reviewed=False)
    assert privacy_information_status(unreviewed).ready is False


def test_privacy_information_requires_an_explicit_dpo_applicability_decision():
    undecided = _complete_settings(privacy_dpo_applicability_confirmed=False)
    assert "privacy_dpo_applicability_confirmed" in privacy_information_status(undecided).missing_fields

    required_without_contact = _complete_settings(privacy_dpo_required=True)
    assert "privacy_dpo_contact" in privacy_information_status(required_without_contact).missing_fields


def test_full_privacy_page_escapes_configured_information_only():
    configured = _complete_settings(privacy_controller_identity="<Responsable>")
    page = render_full_privacy_page(configured)
    assert "&lt;Responsable&gt;" in page
    assert "<Responsable>" not in page


def test_privacy_route_and_readiness_fail_closed(client, monkeypatch):
    response = client.get("/privacidad")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "datos personales reales" in response.text

    readiness = client.get("/api/admin/readiness", headers={"Authorization": "Bearer test-admin-token"}).json()
    privacy = next(item for item in readiness["checks"] if item["key"] == "privacy_information")
    assert privacy["ok"] is False
    assert privacy["metadata"]["reviewed"] is False
    assert "privacy_controller_identity" in privacy["metadata"]["missing_fields"]

    for name, value in vars(_complete_settings()).items():
        monkeypatch.setattr(settings, name, value)
    assert client.get("/privacidad").status_code == 200
    ready = client.get("/api/admin/readiness", headers={"Authorization": "Bearer test-admin-token"}).json()
    privacy = next(item for item in ready["checks"] if item["key"] == "privacy_information")
    assert privacy["ok"] is True
    assert "privacy_information" not in ready["beta_blockers"]


def test_complete_privacy_notice_stays_noindex_until_public_launch_is_enabled(client, monkeypatch):
    for key, value in vars(_complete_settings()).items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(settings, "public_indexing_enabled", False)
    monkeypatch.setattr(settings, "public_base_url", "")

    response = client.get("/privacidad")

    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
