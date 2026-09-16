from pathlib import Path
import shutil
import subprocess
import tempfile

from fastapi import Response
from sqlalchemy import select

from app.account_tokens import PASSWORD_RESET, PASSWORD_RESET_TTL, issue_action_token
from app.auth import issue_session
from app.auth_models import User, UserSession


OLD_PASSWORD = "original-password-change"
NEW_PASSWORD = "replacement-password-change"
STATIC = Path(__file__).parents[1] / "app" / "static"


def test_password_change_requires_current_password_revokes_sessions_and_reset_links(client, db):
    email = "change-password@example.com"
    registered = client.post(
        "/api/auth/register",
        json={"email": email, "password": OLD_PASSWORD},
    )
    assert registered.status_code == 201
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None

    # Simulate other signed-in devices and an outstanding password-reset link.
    issue_session(db, user, Response())
    issue_session(db, user, Response())
    reset_token = issue_action_token(db, user, purpose=PASSWORD_RESET, ttl=PASSWORD_RESET_TTL)
    db.commit()

    wrong = client.post(
        "/api/auth/password-change",
        json={"current_password": "wrong-password-long-enough", "new_password": NEW_PASSWORD},
    )
    assert wrong.status_code == 401
    assert client.get("/api/auth/me").status_code == 200

    same = client.post(
        "/api/auth/password-change",
        json={"current_password": OLD_PASSWORD, "new_password": OLD_PASSWORD},
    )
    assert same.status_code == 422

    changed = client.post(
        "/api/auth/password-change",
        json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["status"] == "password_updated"
    assert changed.json()["sessions_revoked"] >= 1

    # The response establishes one fresh session while every previous session is revoked.
    db.expire_all()
    user = db.scalar(select(User).where(User.email == email))
    sessions = db.scalars(select(UserSession).where(UserSession.user_id == user.id)).all()
    active = [row for row in sessions if row.revoked_at is None]
    assert len(active) == 1
    assert client.get("/api/auth/me").status_code == 200

    # A reset link issued before the password change must no longer work.
    rejected_reset = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "password": "another-password-value"},
    )
    assert rejected_reset.status_code == 400

    assert client.post("/api/auth/logout").status_code == 200
    assert client.post(
        "/api/auth/login", json={"email": email, "password": OLD_PASSWORD}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": email, "password": NEW_PASSWORD}
    ).status_code == 200


def test_password_change_rejects_extra_fields(client):
    client.post(
        "/api/auth/register",
        json={"email": "extra-password@example.com", "password": OLD_PASSWORD},
    )
    response = client.post(
        "/api/auth/password-change",
        json={
            "current_password": OLD_PASSWORD,
            "new_password": NEW_PASSWORD,
            "admin": True,
        },
    )
    assert response.status_code == 422


def test_password_change_ui_is_loaded_and_keeps_passwords_out_of_browser_storage():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "account_password.js").read_text(encoding="utf-8")
    assert "/demo/account_password.js" in loader
    assert "mcr-account-password" in loader
    assert "/api/auth/password-change" in script
    assert "current-password" in script
    assert "new-password" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_password_change_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "account_password.js"]:
        script = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
