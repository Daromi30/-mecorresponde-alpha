"""Public identity boundary for the synthetic-only demo (fictional identities)."""

from sqlalchemy import select

import app.routers.auth as auth_router
from app.auth_models import AuthThrottleState, EmailActionToken, User, UserSession
from app.auth_throttle import login_throttle
from app.config import settings
from app.models import AuditEvent
from app.real_beta_gate import REAL_BETA_LAUNCH_REVIEW_COMPLETE


def test_registration_is_closed_without_any_identity_persistence(client, db, caplog):
    email = "new-fictional-identity@example.test"
    password = "fictional-secret-password-123"
    payload = {"email": email, "password": password}
    for _ in range(2):
        response = client.post("/api/auth/register", json=payload)
        assert response.status_code == 503
        assert response.json() == {"detail": "Account registration is not available"}
        assert email not in response.text and password not in response.text

    for model in (User, UserSession, EmailActionToken, AuthThrottleState, AuditEvent):
        assert db.scalars(select(model)).all() == []
    assert email not in caplog.text
    assert password not in caplog.text


def test_registration_has_no_header_query_body_or_legacy_demo_escape(client, db):
    payload = {
        "email": "bypass-fictional@example.test",
        "password": "fictional-secret-password-123",
        "internal_fixture": True,
        "mode": "PRIVATE_REAL_BETA",
    }
    for url in (
        "/api/auth/register",
        "/api/auth/register?allow_registration=true",
        "/demo/api/auth/register",
    ):
        response = client.post(url, json=payload, headers={"X-Internal-Fixture": "true"})
        assert response.status_code in {404, 405, 503}
        assert response.status_code != 201
    assert client.post("/api/real-beta/invitations/accept", json={"token": "x" * 43}).status_code == 401
    assert client.post("/api/real-beta/cases", json={"message": "fictional"}).status_code == 401
    assert db.scalars(select(User)).all() == []
    assert db.scalars(select(UserSession)).all() == []


def test_unknown_login_is_non_enumerating_and_does_not_persist_digest(client, db, monkeypatch):
    known = "known-fictional@example.test"
    unknown = "unknown-fictional@example.test"
    password = "correct-fictional-password-123"
    wrong = "incorrect-fictional-password-123"
    client.historical_account(known, password)
    client.post("/api/auth/logout")

    cryptographic_work = []
    original_hash = auth_router.hash_password

    def record_hash(value):
        cryptographic_work.append(value)
        return original_hash(value)

    monkeypatch.setattr(auth_router, "hash_password", record_hash)
    nonexistent = client.post("/api/auth/login", json={"email": unknown, "password": wrong})
    incorrect = client.post("/api/auth/login", json={"email": known, "password": wrong})
    assert nonexistent.status_code == incorrect.status_code == 401
    assert nonexistent.json() == incorrect.json() == {"detail": "Invalid email or password"}
    assert cryptographic_work == [wrong]
    assert db.get(AuthThrottleState, login_throttle._key(unknown)) is None
    assert db.get(AuthThrottleState, login_throttle._key(known)) is not None
    assert db.scalars(select(UserSession).where(UserSession.revoked_at.is_(None))).all() == []


def test_existing_identity_throttle_still_blocks_brute_force(client, db):
    email = "protected-fictional@example.test"
    client.historical_account(email, "correct-fictional-password-123")
    client.post("/api/auth/logout")
    old_limit = login_throttle.limit
    login_throttle.limit = 2
    try:
        payload = {"email": email, "password": "incorrect-fictional-password-123"}
        assert client.post("/api/auth/login", json=payload).status_code == 401
        assert client.post("/api/auth/login", json=payload).status_code == 401
        blocked = client.post("/api/auth/login", json=payload)
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) > 0
        assert db.get(AuthThrottleState, login_throttle._key(email)).failure_count == 2
    finally:
        login_throttle.limit = old_limit


def test_historical_account_login_me_logout_and_email_requests_remain_closed(client, db):
    email = "historical-fictional@example.test"
    password = "historical-fictional-password-123"
    user = client.historical_account(email, password).json()["user"]
    assert client.get("/api/auth/me").json()["user"]["id"] == user["id"]
    assert client.get("/api/auth/export").status_code == 200
    assert client.post("/api/auth/email-verification/request").status_code == 503
    assert client.post("/api/auth/password-reset/request", json={"email": email}).status_code == 503
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200
    assert db.get(User, user["id"]) is not None


def test_real_beta_interlocks_and_public_demo_remain_as_before(client):
    assert REAL_BETA_LAUNCH_REVIEW_COMPLETE is False
    assert settings.real_beta_enabled == "false"
    assert settings.real_beta_allowlist == ""
    scenarios = client.get("/api/demo/scenarios")
    assert scenarios.status_code == 200
    assert len(scenarios.json()["scenarios"]) == 4
