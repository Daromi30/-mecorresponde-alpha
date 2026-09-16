from pathlib import Path
import shutil
import subprocess
import tempfile

from fastapi import Response
from sqlalchemy import select

from app.auth import issue_session
from app.auth_models import User, UserSession


PASSWORD = "session-management-password"
STATIC = Path(__file__).parents[1] / "app" / "static"


def test_user_can_list_and_revoke_other_sessions_without_closing_current(client, db):
    email = "session-owner@example.com"
    registered = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert registered.status_code == 201
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None

    # Add two sessions representing other browsers without replacing the client's cookie.
    issue_session(db, user, Response())
    issue_session(db, user, Response())
    db.commit()

    listed = client.get("/api/auth/sessions")
    assert listed.status_code == 200
    body = listed.json()
    assert body["active_count"] == 3
    assert sum(1 for item in body["sessions"] if item["current"]) == 1
    assert all(set(item) == {"current", "created_at", "expires_at"} for item in body["sessions"])

    wrong = client.post(
        "/api/auth/sessions/revoke-others",
        json={"password": "wrong-password-long-enough"},
    )
    assert wrong.status_code == 401
    assert client.get("/api/auth/me").status_code == 200

    revoked = client.post(
        "/api/auth/sessions/revoke-others",
        json={"password": PASSWORD},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["sessions_revoked"] == 2

    listed_after = client.get("/api/auth/sessions").json()
    assert listed_after["active_count"] == 1
    assert listed_after["sessions"][0]["current"] is True
    assert client.get("/api/auth/me").status_code == 200

    db.expire_all()
    active = db.scalars(
        select(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
        )
    ).all()
    assert len(active) == 1


def test_session_management_requires_authentication(client):
    assert client.get("/api/auth/sessions").status_code == 401
    response = client.post(
        "/api/auth/sessions/revoke-others",
        json={"password": PASSWORD},
    )
    assert response.status_code == 401


def test_revoke_other_sessions_rejects_extra_fields(client):
    client.post(
        "/api/auth/register",
        json={"email": "session-extra@example.com", "password": PASSWORD},
    )
    response = client.post(
        "/api/auth/sessions/revoke-others",
        json={"password": PASSWORD, "all_accounts": True},
    )
    assert response.status_code == 422


def test_session_ui_is_loaded_and_keeps_password_out_of_browser_storage():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "account_sessions.js").read_text(encoding="utf-8")
    assert "/demo/account_sessions.js" in loader
    assert "mcr-account-sessions" in loader
    assert "/api/auth/sessions" in script
    assert "/api/auth/sessions/revoke-others" in script
    assert "current-password" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "ubicaciones ni dispositivos" in script


def test_session_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "account_sessions.js"]:
        script = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
