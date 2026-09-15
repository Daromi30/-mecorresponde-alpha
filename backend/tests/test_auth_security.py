from fastapi import Response
from sqlalchemy import select

from app.auth import MAX_ACTIVE_SESSIONS, issue_session
from app.auth_models import User, UserSession
from app.auth_throttle import login_throttle


def test_failed_login_throttle_returns_retry_after_without_ip_tracking(client):
    old_limit = login_throttle.limit
    login_throttle.limit = 2
    login_throttle.reset()
    payload = {"email": "throttle-test@example.com", "password": "wrong-password-long-enough"}
    try:
        assert client.post("/api/auth/login", json=payload).status_code == 401
        assert client.post("/api/auth/login", json=payload).status_code == 401
        blocked = client.post("/api/auth/login", json=payload)
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) >= 1
    finally:
        login_throttle.limit = old_limit
        login_throttle.reset()


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
