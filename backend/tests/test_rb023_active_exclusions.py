from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app import real_beta_gate as gate
from app.auth_models import EmailActionToken, RealBetaInvitation, User
from app.config import settings
from app.documents import save_upload
from app.family_manifest import FAMILY_MANIFEST
from app.models import Case, Document
from app.private_beta_exclusions import (
    AUTOMATIC_EMAIL,
    DOCUMENT_UPLOAD,
    DOWNLOADABLE_DRAFT,
    EXCLUDED_CAPABILITIES,
    PRIVATE_REAL_BETA,
    PrivateRealBetaCapabilityBlocked,
    capability_allowed,
    exclusions_ready,
    require_capability,
    user_capability_allowed,
)
from app.real_beta_gate import utcnow
from release_test_support import eligible_test_release


STATIC = Path(__file__).parents[1] / "app" / "static"
ADMIN_STATIC = Path(__file__).parents[1] / "app" / "admin_static"


def _accepted_member(db, user: User):
    release, _owner, _professional = eligible_test_release(db, [user], families=("E02-A",))
    invitation = RealBetaInvitation(
        token_digest="a" * 64,
        release_id=release.id,
        intended_user_id=user.id,
        status="ACCEPTED",
        expires_at=utcnow() - timedelta(hours=1),
        accepted_by_user_id=user.id,
        accepted_at=utcnow() - timedelta(hours=2),
    )
    db.add(invitation)
    db.commit()
    return release


def test_private_beta_policy_denies_every_exclusion_and_unknown_capability(monkeypatch):
    monkeypatch.setattr(settings, "email_delivery_provider", "configured-provider")
    monkeypatch.setattr(settings, "transactional_email_verified", True)
    monkeypatch.setattr(settings, "document_storage_backend", "configured-provider")

    assert exclusions_ready() is True
    assert EXCLUDED_CAPABILITIES == {
        "document_upload", "external_ai", "automatic_email", "payments", "lane3",
        "external_monitoring", "downloadable_draft", "automatic_submission", "external_action",
    }
    assert all(not capability_allowed(PRIVATE_REAL_BETA, item) for item in EXCLUDED_CAPABILITIES)
    assert capability_allowed(PRIVATE_REAL_BETA, "unknown_future_external_capability") is False
    assert capability_allowed("SYNTHETIC", DOCUMENT_UPLOAD) is True
    with pytest.raises(PrivateRealBetaCapabilityBlocked):
        require_capability(PRIVATE_REAL_BETA, "unknown_future_external_capability")


def test_technical_prerequisites_use_postgres_privacy_and_active_exclusions_only(monkeypatch):
    monkeypatch.setattr(gate, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    monkeypatch.setattr(gate, "privacy_information_status", lambda _settings: SimpleNamespace(ready=True))
    monkeypatch.setattr(gate, "exclusions_ready", lambda: True)
    monkeypatch.setattr(settings, "transactional_email_verified", False)
    monkeypatch.setattr(settings, "document_storage_backend", "local")

    assert gate.technical_prerequisites_ready() is True
    monkeypatch.setattr(gate, "exclusions_ready", lambda: False)
    assert gate.technical_prerequisites_ready() is False
    monkeypatch.setattr(gate, "exclusions_ready", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert gate.technical_prerequisites_ready() is False


def test_direct_upload_service_is_blocked_before_storage_or_persistence(db):
    case = Case(
        family="E02-A", title="Synthetic private exclusion fixture",
        raw_intake="PRIVATE_REAL_BETA:E02-A", mode=PRIVATE_REAL_BETA,
    )
    db.add(case)
    db.commit()

    class UnexpectedStorage:
        @property
        def backend_name(self):
            raise AssertionError("storage provider must not be inspected")

    before = db.scalar(select(func.count()).select_from(Document))
    with pytest.raises(PrivateRealBetaCapabilityBlocked):
        save_upload(
            db, case, "private.txt", "text/plain", b"must not persist",
            storage=UnexpectedStorage(),
        )
    assert db.scalar(select(func.count()).select_from(Document)) == before


def test_private_member_email_provider_calls_are_blocked(client, db, monkeypatch):
    client.historical_account("rb023-member@example.com", "synthetic-strong-password")
    user = db.scalar(select(User).where(User.email == "rb023-member@example.com"))
    _accepted_member(db, user)
    monkeypatch.setattr(settings, "email_delivery_provider", "brevo")
    monkeypatch.setattr(settings, "email_sender_email", "noreply@example.com")
    monkeypatch.setattr(settings, "brevo_api_key", "synthetic-provider-key")
    monkeypatch.setattr(settings, "auth_action_base_url", "https://example.invalid")
    monkeypatch.setattr(settings, "transactional_email_verified", True)

    calls = []

    def unexpected_send(**kwargs):
        calls.append(kwargs)
        raise AssertionError("external email provider must not be called")

    from app.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "send_transactional_email", unexpected_send)
    monkeypatch.setattr(auth_router, "MIN_RESET_REQUEST_SECONDS", 0)

    verification = client.post("/api/auth/email-verification/request")
    assert verification.status_code == 503
    reset = client.post(
        "/api/auth/password-reset/request",
        json={"email": "rb023-member@example.com"},
    )
    assert reset.status_code == 202
    assert calls == []
    assert db.scalar(select(func.count()).select_from(EmailActionToken)) == 0
    assert user_capability_allowed(db, user.id, AUTOMATIC_EMAIL) is False


def test_closed_or_revoked_release_never_reenables_external_capabilities(db):
    user = User(email="closed-member@example.com", password_hash="synthetic-hash")
    db.add(user)
    db.commit()
    release = _accepted_member(db, user)

    release.status = "CLOSED"
    invitation = db.scalar(select(RealBetaInvitation).where(
        RealBetaInvitation.accepted_by_user_id == user.id,
    ))
    invitation.status = "REVOKED"
    invitation.revoked_at = utcnow()
    db.commit()
    assert user_capability_allowed(db, user.id, AUTOMATIC_EMAIL) is False
    assert capability_allowed(PRIVATE_REAL_BETA, DOWNLOADABLE_DRAFT) is False


def test_private_ui_omits_upload_download_and_copy_controls():
    documentation = (STATIC / "documentation.js").read_text(encoding="utf-8")
    handoff = (STATIC / "case_handoff.js").read_text(encoding="utf-8")
    admin_handoff = (ADMIN_STATIC / "case_handoff.js").read_text(encoding="utf-8")
    index = (STATIC / "index.html").read_text(encoding="utf-8")

    assert "currentMode === 'PRIVATE_REAL_BETA'" in documentation
    assert documentation.index("currentMode === 'PRIVATE_REAL_BETA'") < documentation.index("await storageStatus()")
    assert "!caseId || privateBeta" in handoff
    assert "if (!privateBeta)" in admin_handoff
    assert "copyClaimButton').hidden=caseData?.mode==='PRIVATE_REAL_BETA'" in index
    phase_guard = (STATIC / "case_phase_guard.js").read_text(encoding="utf-8")
    assert "!privateBeta && status === 'READY_TO_SUBMIT'" in phase_guard
    # Privacy data portability remains a separate, unaffected capability.
    assert "downloadAccountExport" in (STATIC / "account_export.js").read_text(encoding="utf-8")


def test_no_payment_or_external_ai_routes_are_registered(client):
    paths = {route.path.lower() for route in client.app.routes if hasattr(route, "path")}
    assert not any("payment" in path or "checkout" in path for path in paths)
    assert not any("external-ai" in path or "/llm" in path for path in paths)
    assert len(FAMILY_MANIFEST) == 26
