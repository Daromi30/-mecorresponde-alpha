from sqlalchemy import select

import app.routers.auth as auth_router
from app.auth_models import AuthThrottleState
from app.auth_throttle import password_reset_throttle, verification_email_throttle
from app.config import settings


def configure_email(monkeypatch, sent):
    monkeypatch.setattr(settings, "email_delivery_provider", "brevo")
    monkeypatch.setattr(settings, "brevo_api_key", "test-key")
    monkeypatch.setattr(settings, "email_sender_email", "accounts@example.test")
    monkeypatch.setattr(settings, "auth_action_base_url", "https://alpha.example.test")
    monkeypatch.setattr(settings, "transactional_email_verified", True)
    monkeypatch.setattr(settings, "email_verification_enforced", True)

    def fake_send_transactional_email(*, to_email, subject, text):
        sent.append({"to": to_email, "subject": subject, "text": text})

    monkeypatch.setattr(auth_router, "send_transactional_email", fake_send_transactional_email)


def test_password_reset_requests_are_persistently_rate_limited_without_account_enumeration(
    client, db, monkeypatch
):
    sent = []
    configure_email(monkeypatch, sent)
    email = "unknown-reset@example.com"

    for _ in range(password_reset_throttle.limit):
        response = client.post("/api/auth/password-reset/request", json={"email": email})
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        assert email not in response.text

    blocked = client.post("/api/auth/password-reset/request", json={"email": email})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert sent == []

    row = db.get(AuthThrottleState, password_reset_throttle._key(email))
    assert row is not None
    assert row.failure_count == password_reset_throttle.limit
    assert email not in row.key_hash


def test_verification_email_resends_are_limited_and_confirm_clears_throttle(
    client, db, monkeypatch
):
    sent = []
    configure_email(monkeypatch, sent)
    email = "verify-throttle@example.com"
    registered = client.post(
        "/api/auth/register",
        json={"email": email, "password": "strong-password-for-verification"},
    )
    assert registered.status_code == 201

    for _ in range(verification_email_throttle.limit):
        response = client.post("/api/auth/email-verification/request")
        assert response.status_code == 202
    blocked = client.post("/api/auth/email-verification/request")
    assert blocked.status_code == 429
    assert len(sent) == verification_email_throttle.limit

    # The throttle is namespaced: verification traffic must not create the login key.
    assert db.get(AuthThrottleState, verification_email_throttle._key(email)) is not None
    from app.auth_throttle import login_throttle
    assert db.get(AuthThrottleState, login_throttle._key(email)) is None
