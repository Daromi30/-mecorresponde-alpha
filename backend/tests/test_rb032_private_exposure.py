from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.auth_models import User, UserSession
from app.backoffice_auth import create_reviewer
from app.config import settings
from app.family_manifest import FAMILY_MANIFEST
from app.models import Case


APP_DIR = Path(__file__).parents[1] / "app"


def _private_case(db, user: User) -> Case:
    case = Case(
        user_id=user.id,
        mode="PRIVATE_REAL_BETA",
        status="INTAKE",
        vertical="electricity",
        family="E02-A",
        title="Fixture privada sintética",
        raw_intake="RB032_PRIVATE_SENTINEL",
    )
    db.add(case)
    db.commit()
    return case


def _assert_private_headers(response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"


def test_private_case_auth_cross_user_expiry_and_ids_are_non_enumerating(client, db, monkeypatch):
    monkeypatch.setattr(settings, "public_indexing_enabled", True)
    monkeypatch.setattr(settings, "public_base_url", "https://www.mecorresponde.es")
    client.historical_account("rb032-owner@example.com", "synthetic-owner-password")
    owner = db.scalar(select(User).where(User.email == "rb032-owner@example.com"))
    case = _private_case(db, owner)

    own = client.get(f"/api/cases/{case.id}")
    assert own.status_code == 200
    assert own.json()["id"] == case.id
    _assert_private_headers(own)
    assert own.headers["content-type"].startswith("application/json")
    assert "og:" not in own.text.lower() and "twitter:" not in own.text.lower()

    assert client.post("/api/auth/logout").status_code == 200
    known_anonymous = client.get(f"/api/cases/{case.id}")
    random_anonymous = client.get("/api/cases/00000000-0000-0000-0000-000000000000")
    assert known_anonymous.status_code == random_anonymous.status_code == 404
    assert known_anonymous.json() == random_anonymous.json() == {"detail": "Case not found"}
    assert "RB032_PRIVATE_SENTINEL" not in known_anonymous.text
    _assert_private_headers(known_anonymous)
    _assert_private_headers(random_anonymous)

    client.historical_account("rb032-other@example.com", "synthetic-other-password")
    cross_user = client.get(f"/api/cases/{case.id}")
    assert cross_user.status_code == 404
    assert cross_user.json() == known_anonymous.json()
    assert "RB032_PRIVATE_SENTINEL" not in cross_user.text
    _assert_private_headers(cross_user)

    assert client.post("/api/auth/logout").status_code == 200
    assert client.post("/api/auth/login", json={
        "email": "rb032-owner@example.com", "password": "synthetic-owner-password",
    }).status_code == 200
    sessions = db.scalars(select(UserSession).where(UserSession.user_id == owner.id)).all()
    for session in sessions:
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    expired = client.get(f"/api/cases/{case.id}")
    assert expired.status_code == 404
    assert expired.json() == known_anonymous.json()
    _assert_private_headers(expired)


def test_unauthorized_document_probe_cannot_bypass_case_auth_or_reveal_storage(client, db):
    client.historical_account("rb032-document-owner@example.com", "synthetic-document-password")
    owner = db.scalar(select(User).where(User.email == "rb032-document-owner@example.com"))
    case = _private_case(db, owner)
    assert client.post("/api/auth/logout").status_code == 200

    known = client.post(
        f"/api/cases/{case.id}/documents",
        files={"file": ("probe.txt", b"synthetic", "text/plain")},
    )
    random = client.post(
        "/api/cases/00000000-0000-0000-0000-000000000000/documents",
        files={"file": ("probe.txt", b"synthetic", "text/plain")},
    )
    assert known.status_code == random.status_code == 404
    assert known.json() == random.json() == {"detail": "Case not found"}
    assert "storage" not in known.text.lower() and "persistent" not in known.text.lower()
    _assert_private_headers(known)


def test_account_and_real_beta_errors_and_export_are_private(client, db):
    anonymous_export = client.get("/api/auth/export")
    assert anonymous_export.status_code == 401
    _assert_private_headers(anonymous_export)

    private_create = client.post(
        "/api/real-beta/cases",
        json={"family": "E02-A", "age_18_plus_attested": True},
    )
    assert private_create.status_code == 401
    _assert_private_headers(private_create)

    client.historical_account("rb032-export@example.com", "synthetic-export-password")
    user = db.scalar(select(User).where(User.email == "rb032-export@example.com"))
    case = _private_case(db, user)
    own_export = client.get("/api/auth/export")
    assert own_export.status_code == 200
    assert own_export.headers["content-disposition"].startswith("attachment;")
    assert any(row["id"] == case.id for row in own_export.json()["cases"])
    _assert_private_headers(own_export)


def test_backoffice_requires_identity_and_never_caches_private_data(client, db):
    client.historical_account("rb032-backoffice-owner@example.com", "synthetic-backoffice-owner")
    owner = db.scalar(select(User).where(User.email == "rb032-backoffice-owner@example.com"))
    case = _private_case(db, owner)

    anonymous = client.get(f"/api/admin/cases/{case.id}")
    random = client.get("/api/admin/cases/00000000-0000-0000-0000-000000000000")
    assert anonymous.status_code == random.status_code == 401
    assert "RB032_PRIVATE_SENTINEL" not in anonymous.text
    _assert_private_headers(anonymous)

    legacy_token = client.get(
        f"/api/admin/cases/{case.id}",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert legacy_token.status_code == 404
    assert "RB032_PRIVATE_SENTINEL" not in legacy_token.text
    _assert_private_headers(legacy_token)

    create_reviewer(db, "rb032operator", "synthetic-operator-password", "operator")
    db.commit()
    login = client.post("/api/backoffice-auth/login", json={
        "login_id": "rb032operator", "password": "synthetic-operator-password",
    })
    assert login.status_code == 200
    authorized = client.get(f"/api/admin/cases/{case.id}")
    assert authorized.status_code == 200
    assert authorized.json()["id"] == case.id
    _assert_private_headers(authorized)

    shell = client.get("/backoffice/")
    assert shell.status_code == 200
    _assert_private_headers(shell)
    assert '<meta name="robots" content="noindex,nofollow,noarchive"' in shell.text
    assert "RB032_PRIVATE_SENTINEL" not in shell.text
    assert "property=\"og:" not in shell.text.lower()


def test_robots_sitemap_and_public_seo_stay_separated(client, monkeypatch):
    monkeypatch.setattr(settings, "public_indexing_enabled", True)
    monkeypatch.setattr(settings, "public_base_url", "https://www.mecorresponde.es")

    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Disallow: /api/" in robots.text
    assert "Disallow: /backoffice/" in robots.text
    assert "Sitemap: https://www.mecorresponde.es/sitemap.xml" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    for forbidden in ("/api/", "/backoffice", "/demo", "/auth", "/cases", "real-beta", "export"):
        assert forbidden not in sitemap.text
    assert sitemap.text.count("<url><loc>") == len(FAMILY_MANIFEST) + 1

    public_page = client.get("/")
    assert public_page.status_code == 200
    assert "x-robots-tag" not in public_page.headers
    assert public_page.headers.get("cache-control") != "no-store"
    assert '<meta name="robots" content="index,follow">' in public_page.text


def test_public_api_documentation_is_not_exposed_and_cross_site_errors_are_private(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.headers["x-robots-tag"] == "noindex, nofollow"

    blocked = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "synthetic-password"},
        headers={"Origin": "https://attacker.invalid", "Sec-Fetch-Site": "cross-site"},
    )
    assert blocked.status_code == 403
    _assert_private_headers(blocked)

    private_ui = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    assert '<meta name="robots" content="noindex,nofollow,noarchive">' in private_ui
    assert "property=\"og:" not in private_ui.lower()


def test_twenty_six_families_remain_intact():
    assert len(FAMILY_MANIFEST) == 26
