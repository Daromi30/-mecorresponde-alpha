from fastapi import Response
from sqlalchemy import select

from app.auth import MAX_ACTIVE_SESSIONS, issue_session
from app.auth_models import AuthThrottleState, User, UserSession
from app.auth_throttle import LoginThrottle, login_throttle


def test_failed_login_throttle_returns_retry_after_without_ip_tracking(client, db):
    old_limit = login_throttle.limit
    login_throttle.limit = 2
    login_throttle.reset(db)
    db.commit()
    payload = {"email": "throttle-test@example.com", "password": "wrong-password-long-enough"}
    try:
        assert client.post("/api/auth/login", json=payload).status_code == 401
        assert client.post("/api/auth/login", json=payload).status_code == 401
        blocked = client.post("/api/auth/login", json=payload)
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) >= 1

        rows = db.scalars(select(AuthThrottleState)).all()
        assert len(rows) == 1
        assert rows[0].failure_count == 2
        assert "throttle-test@example.com" not in rows[0].key_hash
    finally:
        login_throttle.limit = old_limit
        login_throttle.reset(db)
        db.commit()


def test_throttle_state_survives_new_throttle_instance(client, db):
    email = "persistent-throttle@example.com"
    payload = {"email": email, "password": "wrong-password-long-enough"}
    old_limit = login_throttle.limit
    login_throttle.limit = 2
    login_throttle.reset(db)
    db.commit()
    try:
        assert client.post("/api/auth/login", json=payload).status_code == 401
        assert client.post("/api/auth/login", json=payload).status_code == 401

        restarted_worker = LoginThrottle(limit=2, window_seconds=login_throttle.window_seconds)
        try:
            restarted_worker.check(db, email)
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 429
        else:
            raise AssertionError("A new worker instance must observe persisted throttle state")
    finally:
        login_throttle.limit = old_limit
        login_throttle.reset(db)
        db.commit()


def test_successful_login_clears_persisted_throttle_state(client, db):
    email = "clear-throttle@example.com"
    password = "strong-password-for-throttle"
    assert client.post("/api/auth/register", json={"email": email, "password": password}).status_code == 201
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post("/api/auth/login", json={"email": email, "password": "wrong-password-long-enough"}).status_code == 401
    assert db.get(AuthThrottleState, login_throttle._key(email)) is not None

    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200
    db.expire_all()
    assert db.get(AuthThrottleState, login_throttle._key(email)) is None


def test_successful_account_is_limited_to_five_active_sessions(client, db):
    registered = client.post(
        "/api/auth/register",
        json={"email": "sessions@example.com", "password": "strong-password-for-sessions"},
    )
    assert registered.status_code == 201
    user = db.scalar(select(User).where(User.email == "sessions@example.com"))
    assert user is not None

    for _ in range(MAX_ACTIVE_SESSIONS + 1):
        issue_session(db, user, Response())
        db.flush()
    db.commit()

    active = db.scalars(
        select(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
        )
    ).all()
    assert len(active) == MAX_ACTIVE_SESSIONS


def test_case_api_is_not_cacheable_and_has_browser_safety_headers(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]

    case_response = client.get(f"/api/cases/{case_id}")
    assert case_response.status_code == 200
    assert case_response.headers["cache-control"] == "no-store"
    assert case_response.headers["x-content-type-options"] == "nosniff"
    assert case_response.headers["x-frame-options"] == "DENY"
    assert case_response.headers["referrer-policy"] == "no-referrer"
    assert "geolocation=()" in case_response.headers["permissions-policy"]


def test_product_ui_has_restrictive_content_security_policy(client):
    response = client.get("/demo/")
    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self'" in csp


def test_untrusted_browser_origin_cannot_create_state(client):
    blocked = client.post(
        "/api/cases",
        json={"message": "Intento cross-site"},
        headers={
            "Origin": "https://attacker.invalid",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Cross-site state-changing request blocked"
    assert blocked.headers["cache-control"] == "no-store"


def test_cross_site_fetch_without_origin_is_blocked_for_unsafe_methods(client):
    blocked = client.post(
        "/api/cases",
        json={"message": "Intento sin Origin"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert blocked.status_code == 403


def test_configured_cors_origin_remains_allowed_for_browser_writes(client):
    allowed = client.post(
        "/api/cases",
        json={"message": "Compra online no entregada"},
        headers={
            "Origin": "http://localhost:3000",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert allowed.status_code == 200


def test_cross_site_read_is_not_blocked_by_write_guard(client):
    response = client.get(
        "/health",
        headers={
            "Origin": "https://attacker.invalid",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert response.status_code == 200
