from pathlib import Path
import shutil
import subprocess
import tempfile

from app.services_v2 import create_case, create_human_review


ADMIN = {"Authorization": "Bearer test-admin-token"}
STATIC = Path(__file__).parents[1] / "app" / "admin_static"


def test_admin_handoff_requires_admin_and_returns_case_package(client, db):
    case = create_case(db, "La factura de luz es incorrecta y me han cobrado de más")
    create_human_review(
        db,
        case,
        reason="TEST_REVIEW_REQUIRED",
        priority="HIGH",
        context={"source": "test"},
    )
    db.commit()

    unauthenticated = client.get(f"/api/admin/cases/{case.id}/handoff")
    assert unauthenticated.status_code == 401

    response = client.get(f"/api/admin/cases/{case.id}/handoff", headers=ADMIN)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["package_version"] == 1
    assert body["case"]["id"] == case.id
    assert body["case"]["family"] == "E02-A"
    assert body["open_human_review_count"] == 1
    assert "internal_audit_payloads" in body["excluded_internal_data"]
    assert response.headers["cache-control"] == "no-store"


def test_backoffice_handoff_ui_is_loaded_and_javascript_parses():
    loader = (STATIC / "readiness.js").read_text(encoding="utf-8")
    script = (STATIC / "case_handoff.js").read_text(encoding="utf-8")

    assert "case_handoff.js" in loader
    assert "mcr-admin-handoff" in loader
    assert "script.async = false" in loader
    assert "/api/admin/cases/" in script
    assert "/handoff" in script
    assert "Descargar paquete estructurado" in script
    assert "legal_provenance" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script

    node = shutil.which("node")
    if not node:
        return
    for filename in ["readiness.js", "case_handoff.js"]:
        source = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(source)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
