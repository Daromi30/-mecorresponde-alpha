from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import tempfile

from sqlalchemy import select

import app.routers.auth as auth_router
from app.auth_models import EmailActionToken, User
from app.config import settings


PASSWORD = "original-password-123"
NEW_PASSWORD = "replacement-password-456"
STATIC = Path(__file__).parents[1] / "app" / "static"


def configure_email(monkeypatch, sent):
    monkeypatch.setattr(settings, "email_delivery_provider", "brevo")
    monkeypatch.setattr(settings, "brevo_api_key", "test-key")
    monkeypatch.setattr(settings, "email_sender_email", "accounts@example.test")
    monkeypatch.setattr(settings, "auth_action_base_url", "https://alpha.example.test")
    monkeypatch.setattr(settings, "transactional_email_verified", True)
    monkeypatch.setattr(settings, "email_verification_enforced", True)

    def fake_send_transactional_email(*, to_email, subject, text):
        sent.append({"to": to_email, "subject": subject, "text": text})
        return None

    monkeypatch.setattr(auth_router, "send_transactional_email", fake_send_transactional_email)


def register(client, email="recover@example.com"):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


def token_from_mail(text: str, key: str) -> str:
    match = re.search(rf"#{re.escape(key)}=([^\s]+)", text)
    assert match, text
    return match.group(1)


def test_recovery_capabilities_fail_closed_without_provider(client):
    body = client.get("/api/auth/capabilities").json()
    assert body == {
        "transactional_email_operational": False,
        "password_recovery_available": False,
        "email_verification_available": False,
        "email_verification_enforced": False,
    }
    existing = client.post(
        "/api/auth/password-reset/request",
        json={"email": "nobody@example.com"},
    )
    assert existing.status_code == 503


def test_email_verification_uses_hashed_one_time_token_and_gates_case_claim(client, db, monkeypatch):
    sent = []
    configure_email(monkeypatch, sent)
    user = register(client)
    assert user["email_verified"] is False

    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    blocked = client.post(f"/api/cases/{case_id}/claim")
    assert blocked.status_code == 403

    request = client.post("/api/auth/email-verification/request")
    assert request.status_code == 202, request.text
    assert request.json() == {"status": "sent"}
    assert len(sent) == 1
    assert sent[0]["to"] == "recover@example.com"
    assert "?verify-email=" not in sent[0]["text"]
    token = token_from_mail(sent[0]["text"], "verify-email")

    row = db.scalar(select(EmailActionToken).where(EmailActionToken.purpose == "VERIFY_EMAIL"))
    assert row is not None
    assert token not in row.token_hash
    assert len(row.token_hash) == 64

    confirmed = client.post(
        "/api/auth/email-verification/confirm",
        json={"token": token},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["user"]["email_verified"] is True
    assert client.post(
        "/api/auth/email-verification/confirm",
        json={"token": token},
    ).status_code == 400

    claimed = client.post(f"/api/cases/{case_id}/claim")
    assert claimed.status_code == 200, claimed.text


def test_requesting_new_verification_invalidates_previous_link(client, db, monkeypatch):
    sent = []
    configure_email(monkeypatch, sent)
    register(client)
    assert client.post("/api/auth/email-verification/request").status_code == 202
    first = token_from_mail(sent[-1]["text"], "verify-email")
    assert client.post("/api/auth/email-verification/request").status_code == 202
    second = token_from_mail(sent[-1]["text"], "verify-email")
    assert first != second
    assert client.post("/api/auth/email-verification/confirm", json={"token": first}).status_code == 400
    assert client.post("/api/auth/email-verification/confirm", json={"token": second}).status_code == 200


def test_expired_verification_token_is_rejected(client, db, monkeypatch):
    sent = []
    configure_email(monkeypatch, sent)
    register(client)
    assert client.post("/api/auth/email-verification/request").status_code == 202
    token = token_from_mail(sent[-1]["text"], "verify-email")
    row = db.scalar(select(EmailActionToken).where(EmailActionToken.purpose == "VERIFY_EMAIL"))
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert client.post("/api/auth/email-verification/confirm", json={"token": token}).status_code == 400


def test_password_reset_is_generic_one_time_and_revokes_sessions(client, db, monkeypatch):
    sent = []
    configure_email(monkeypatch, sent)
    register(client)

    unknown = client.post(
        "/api/auth/password-reset/request",
        json={"email": "does-not-exist@example.com"},
    )
    assert unknown.status_code == 202
    assert "does-not-exist" not in unknown.text
    assert sent == []

    request = client.post(
        "/api/auth/password-reset/request",
        json={"email": "recover@example.com"},
    )
    assert request.status_code == 202, request.text
    assert request.json()["status"] == "accepted"
    assert "recover@example.com" not in request.text
    token = token_from_mail(sent[-1]["text"], "reset-password")
    assert "?reset-password=" not in sent[-1]["text"]

    row = db.scalar(select(EmailActionToken).where(EmailActionToken.purpose == "PASSWORD_RESET"))
    assert row is not None
    assert token not in row.token_hash

    reset = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "password": NEW_PASSWORD},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json() == {"status": "password_updated"}
    assert client.get("/api/auth/me").status_code == 401
    assert client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "password": NEW_PASSWORD},
    ).status_code == 400

    assert client.post(
        "/api/auth/login",
        json={"email": "recover@example.com", "password": PASSWORD},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "recover@example.com", "password": NEW_PASSWORD},
    ).status_code == 200


def test_account_recovery_ui_is_dormant_until_capability_and_keeps_tokens_out_of_urls():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "account_recovery.js").read_text(encoding="utf-8")
    assert "/demo/account_recovery.js" in loader
    assert "mcr-account-recovery" in loader
    assert "/api/auth/capabilities" in script
    assert "password_recovery_available" in script
    assert "/api/auth/password-reset/request" in script
    assert "/api/auth/password-reset/confirm" in script
    assert "/api/auth/email-verification/request" in script
    assert "/api/auth/email-verification/confirm" in script
    assert "history.replaceState" in script
    assert "verify-email" in script and "reset-password" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_account_recovery_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "account_recovery.js"]:
        script = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
