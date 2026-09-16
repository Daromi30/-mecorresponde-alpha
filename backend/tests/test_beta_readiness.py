from pathlib import Path
import shutil
import subprocess
import tempfile


ADMIN = {"Authorization": "Bearer test-admin-token"}
ADMIN_STATIC = Path(__file__).parents[1] / "app" / "admin_static"


def test_readiness_requires_admin(client):
    assert client.get("/api/admin/readiness").status_code == 401


def test_readiness_separates_closed_beta_public_beta_and_launch_blockers(client):
    response = client.get("/api/admin/readiness", headers=ADMIN)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) >= {
        "full_closed_beta_ready",
        "public_beta_ready",
        "public_launch_ready",
        "beta_blockers",
        "public_beta_blockers",
        "public_launch_blockers",
        "checks",
    }
    checks = {item["key"]: item for item in body["checks"]}
    assert checks["resolution_family_registry"]["ok"] is True
    assert checks["reviewed_legal_catalog"]["ok"] is True
    assert checks["protected_backoffice"]["ok"] is True

    # Tests deliberately run on SQLite/local storage. The readiness endpoint must
    # therefore fail closed instead of pretending the deployment is beta-ready.
    assert checks["persistent_database"]["ok"] is False
    assert checks["persistent_document_storage"]["ok"] is False
    assert "persistent_database" in body["beta_blockers"]
    assert "persistent_document_storage" in body["beta_blockers"]

    # Recovery is no longer a guessed capability: CI creates a real PostgreSQL
    # dump and restores it into an isolated disposable database on every run.
    assert checks["database_recovery"]["ok"] is True
    assert checks["database_recovery"]["severity"] == "BETA_BLOCKER"
    assert checks["database_recovery"]["metadata"]["verification"] == "postgresql_custom_dump_isolated_restore_ci"
    assert "database_recovery" not in body["beta_blockers"]

    # The separate infrastructure lifecycle decision remains intentionally open.
    assert checks["database_lifecycle_managed"]["ok"] is False
    assert checks["database_lifecycle_managed"]["severity"] == "BETA_BLOCKER"
    assert "database_lifecycle_managed" in body["beta_blockers"]

    # Privacy information is intentionally not published until the real controller,
    # purposes, bases, retention and recipients have been reviewed. This is a blocker
    # for any beta using real personal data, not something the product may guess.
    assert checks["privacy_information"]["ok"] is False
    assert checks["privacy_information"]["severity"] == "BETA_BLOCKER"
    assert "privacy_information" in body["beta_blockers"]
    assert checks["privacy_information"]["metadata"]["official_guidance"]

    assert checks["password_recovery"]["ok"] is False
    assert checks["email_verification"]["ok"] is False
    assert "password_recovery" in body["public_beta_blockers"]
    assert "email_verification" in body["public_beta_blockers"]


def test_readiness_response_contains_no_case_or_user_data(client):
    body = client.get("/api/admin/readiness", headers=ADMIN).json()
    text = str(body).lower()
    assert "email@" not in text
    assert "raw_intake" not in text
    assert "password_hash" not in text


def test_backoffice_loads_readiness_cockpit():
    structured = (ADMIN_STATIC / "structured_review.js").read_text(encoding="utf-8")
    readiness = (ADMIN_STATIC / "readiness.js").read_text(encoding="utf-8")
    assert "readiness.js" in structured
    assert "data-mcr-readiness" in structured
    assert "/api/admin/readiness" in readiness
    assert "Bloqueantes de beta completa" in readiness


def test_readiness_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["structured_review.js", "readiness.js"]:
        script = (ADMIN_STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
