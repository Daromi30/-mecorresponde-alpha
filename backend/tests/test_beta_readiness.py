from pathlib import Path
import shutil
import subprocess
import tempfile


ADMIN = {"Authorization": "Bearer test-admin-token"}
ADMIN_STATIC = Path(__file__).parents[1] / "app" / "admin_static"
DOCS = Path(__file__).parents[2] / "docs"
MAIN = Path(__file__).parents[1] / "app" / "main.py"
ALEMBIC_ENV = Path(__file__).parents[1] / "alembic" / "env.py"


def test_readiness_requires_admin(client):
    assert client.get("/api/admin/readiness").status_code == 401


def test_readiness_separates_internal_real_data_public_beta_and_launch_blockers(client):
    response = client.get("/api/admin/readiness", headers=ADMIN)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) >= {
        "synthetic_internal_beta_ready",
        "full_closed_beta_ready",
        "public_beta_ready",
        "public_launch_ready",
        "internal_beta_blockers",
        "beta_blockers",
        "public_beta_blockers",
        "public_launch_blockers",
        "checks",
    }
    checks = {item["key"]: item for item in body["checks"]}
    assert checks["resolution_family_registry"]["ok"] is True
    assert checks["reviewed_legal_catalog"]["ok"] is True
    assert checks["protected_backoffice"]["ok"] is True
    assert checks["all_family_acceptance"]["ok"] is True
    assert checks["guided_browser_input_contract"]["ok"] is True
    assert checks["saved_account_resolution_journey"]["ok"] is True

    # Tests deliberately run on SQLite/local storage. Internal deployed beta therefore
    # remains false here because the runtime datastore itself is not persistent.
    assert checks["persistent_database"]["ok"] is False
    assert checks["persistent_database"]["severity"] == "INTERNAL_BETA_BLOCKER"
    assert body["synthetic_internal_beta_ready"] is False
    assert "persistent_database" in body["internal_beta_blockers"]
    assert "persistent_database" in body["beta_blockers"]

    # Document storage is not required for synthetic internal testing, but it remains
    # a blocker before the product accepts real documents/data in a full closed beta.
    assert checks["persistent_document_storage"]["ok"] is False
    assert checks["persistent_document_storage"]["severity"] == "BETA_BLOCKER"
    assert "persistent_document_storage" not in body["internal_beta_blockers"]
    assert "persistent_document_storage" in body["beta_blockers"]

    # Recovery is no longer a guessed capability: CI creates a real PostgreSQL
    # dump and restores it into an isolated disposable database on every run.
    assert checks["database_recovery"]["ok"] is True
    assert checks["database_recovery"]["severity"] == "INTERNAL_BETA_BLOCKER"
    assert checks["database_recovery"]["metadata"]["verification"] == "postgresql_custom_dump_isolated_restore_ci"
    assert "database_recovery" not in body["internal_beta_blockers"]

    # Infrastructure lifecycle and privacy remain intentionally separate from a
    # synthetic-data test. They still block any beta using real personal data.
    assert checks["database_lifecycle_managed"]["ok"] is False
    assert checks["database_lifecycle_managed"]["severity"] == "BETA_BLOCKER"
    assert "database_lifecycle_managed" not in body["internal_beta_blockers"]
    assert "database_lifecycle_managed" in body["beta_blockers"]

    assert checks["privacy_information"]["ok"] is False
    assert checks["privacy_information"]["severity"] == "BETA_BLOCKER"
    assert "privacy_information" not in body["internal_beta_blockers"]
    assert "privacy_information" in body["beta_blockers"]
    assert checks["privacy_information"]["metadata"]["official_guidance"]

    assert checks["password_recovery"]["ok"] is False
    assert checks["email_verification"]["ok"] is False
    assert "password_recovery" in body["public_beta_blockers"]
    assert "email_verification" in body["public_beta_blockers"]


def test_database_readiness_document_matches_recovery_and_lifecycle_contract():
    document = (DOCS / "database-beta-readiness.md").read_text(encoding="utf-8")
    assert "DATABASE_RECOVERY_AVAILABLE = True" in document
    assert "DATABASE_LIFECYCLE_MANAGED = False" in document
    assert "ruta técnica de copia y restauración está probada" in document
    assert "programación automática" in document
    assert "DATABASE_RECOVERY_AVAILABLE`\n" not in document


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
    assert "Beta interna con datos ficticios lista para prueba manual" in readiness
    assert "Pendientes antes de datos reales" in readiness


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


def test_startup_logs_same_internal_readiness_used_by_admin_route():
    source = MAIN.read_text(encoding="utf-8")
    assert "beta_readiness as compute_beta_readiness" in source
    assert "readiness = compute_beta_readiness(db)" in source
    assert "internal_beta_readiness: unavailable" in source
    assert "synthetic_internal_beta_ready=%s internal_beta_blockers=%s" in source


def test_alembic_preserves_application_loggers_for_runtime_readiness_evidence():
    source = ALEMBIC_ENV.read_text(encoding="utf-8")
    assert "fileConfig(config.config_file_name, disable_existing_loggers=False)" in source
