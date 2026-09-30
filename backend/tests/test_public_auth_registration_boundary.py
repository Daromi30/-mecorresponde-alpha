"""Public identity boundary for the synthetic-only demo (fictional identities)."""

from datetime import datetime, timedelta, timezone

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


def test_existing_identity_throttle_blocks_internally_with_uniform_public_error(client, db):
    email = "protected-fictional@example.test"
    unknown = "unregistered-fictional@example.test"
    correct_password = "correct-fictional-password-123"
    client.historical_account(email, correct_password)
    client.post("/api/auth/logout")
    old_limit = login_throttle.limit
    login_throttle.limit = 2
    try:
        payload = {"email": email, "password": "incorrect-fictional-password-123"}
        unknown_payload = {"email": unknown, "password": payload["password"]}
        for _ in range(3):
            unknown_response = client.post("/api/auth/login", json=unknown_payload)
            assert unknown_response.status_code == 401
            assert unknown_response.json() == {"detail": "Invalid email or password"}
            assert "retry-after" not in unknown_response.headers
            assert db.get(AuthThrottleState, login_throttle._key(unknown)) is None

        first = client.post("/api/auth/login", json=payload)
        second = client.post("/api/auth/login", json=payload)
        assert first.status_code == second.status_code == 401
        assert first.json() == second.json() == unknown_response.json()
        blocked = client.post("/api/auth/login", json=payload)
        assert blocked.status_code == 401
        assert blocked.json() == unknown_response.json()
        assert "retry-after" not in blocked.headers
        row = db.get(AuthThrottleState, login_throttle._key(email))
        assert row.failure_count == 2
        assert row.blocked_until is not None

        # A correct password cannot bypass the live internal lock or create a session.
        correct_while_blocked = client.post(
            "/api/auth/login", json={"email": email, "password": correct_password}
        )
        assert correct_while_blocked.status_code == 401
        assert correct_while_blocked.json() == unknown_response.json()
        assert "retry-after" not in correct_while_blocked.headers
        assert db.get(AuthThrottleState, login_throttle._key(email)).failure_count == 2
        assert db.scalars(select(UserSession).where(UserSession.revoked_at.is_(None))).all() == []

        # Expire the existing window without changing the throttle implementation.
        expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        row.window_started_at = expired_at - timedelta(seconds=login_throttle.window_seconds)
        row.blocked_until = expired_at
        db.commit()
        recovered = client.post(
            "/api/auth/login", json={"email": email, "password": correct_password}
        )
        assert recovered.status_code == 200
        assert db.get(AuthThrottleState, login_throttle._key(email)) is None
    finally:
        login_throttle.limit = old_limit


def test_blocked_and_unknown_login_both_do_pbkdf2_without_password_verification(
    client, db, monkeypatch
):
    email = "locked-crypto-fictional@example.test"
    password = "correct-fictional-password-123"
    wrong = "incorrect-fictional-password-123"
    client.historical_account(email, password)
    client.post("/api/auth/logout")
    old_limit = login_throttle.limit
    login_throttle.limit = 1
    try:
        assert client.post("/api/auth/login", json={"email": email, "password": wrong}).status_code == 401
        calls = []
        original_hash = auth_router.hash_password

        def record_hash(value):
            calls.append(value)
            return original_hash(value)

        def unexpected_verification(*args):
            raise AssertionError("Blocked login must not check the password hash")

        monkeypatch.setattr(auth_router, "hash_password", record_hash)
        monkeypatch.setattr(auth_router, "verify_password", unexpected_verification)
        blocked = client.post("/api/auth/login", json={"email": email, "password": password})
        unknown = client.post(
            "/api/auth/login",
            json={"email": "unknown-crypto-fictional@example.test", "password": wrong},
        )
        assert blocked.status_code == unknown.status_code == 401
        assert blocked.json() == unknown.json()
        assert calls == [password, wrong]
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
