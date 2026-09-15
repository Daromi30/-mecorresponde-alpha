from pathlib import Path
import shutil
import subprocess
import tempfile

from sqlalchemy import select

import app.case_lifecycle as lifecycle
from app.models import Case, Document, Fact
from app.security import CaseAccess


STATIC = Path(__file__).parents[1] / "app" / "static"
PASSWORD = "case-delete-password"


def create_case(client):
    response = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def register(client, email):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def test_anonymous_case_can_be_deleted_only_with_explicit_confirmation(client, db):
    case_id = create_case(client)
    fact = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": "electricity.billing.synthetic_note", "value": "test", "state": "confirmed", "user_confirmed": True},
    )
    assert fact.status_code == 200

    bad = client.request(
        "DELETE",
        f"/api/cases/{case_id}",
        json={"confirmation": "NO"},
    )
    assert bad.status_code == 422
    assert db.get(Case, case_id) is not None

    response = client.request(
        "DELETE",
        f"/api/cases/{case_id}",
        json={"confirmation": "DELETE"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "deleted"
    assert response.json()["documents_deleted"] == 0
    assert db.get(Case, case_id) is None
    assert db.get(CaseAccess, case_id) is None
    assert db.scalars(select(Fact).where(Fact.case_id == case_id)).all() == []


def test_account_owner_can_delete_one_case_without_deleting_account(client, db):
    register(client, "owner@example.com")
    case_id = create_case(client)
    assert client.post(f"/api/cases/{case_id}/claim").status_code == 200

    deleted = client.request(
        "DELETE",
        f"/api/cases/{case_id}",
        json={"confirmation": "DELETE"},
    )
    assert deleted.status_code == 200, deleted.text
    assert db.get(Case, case_id) is None
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/auth/cases").json()["cases"] == []


def test_another_account_cannot_delete_owned_case(client, db):
    register(client, "first-owner@example.com")
    case_id = create_case(client)
    assert client.post(f"/api/cases/{case_id}/claim").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200

    register(client, "second-owner@example.com")
    denied = client.request(
        "DELETE",
        f"/api/cases/{case_id}",
        json={"confirmation": "DELETE"},
    )
    assert denied.status_code in {401, 403, 404}
    assert db.get(Case, case_id) is not None


def test_case_deletion_fails_closed_when_document_object_cannot_be_removed(client, db, monkeypatch):
    case_id = create_case(client)
    document = Document(
        case_id=case_id,
        storage_key=f"originals/{case_id}/aa/test",
        original_filename="synthetic.txt",
        mime_type="text/plain",
        sha256="a" * 64,
    )
    db.add(document)
    db.commit()

    class BrokenStorage:
        def delete_bytes(self, key):
            raise RuntimeError("synthetic storage failure")

    monkeypatch.setattr(lifecycle, "get_document_storage", lambda: BrokenStorage())
    response = client.request(
        "DELETE",
        f"/api/cases/{case_id}",
        json={"confirmation": "DELETE"},
    )
    assert response.status_code == 503
    assert db.get(Case, case_id) is not None
    assert db.get(Document, document.id) is not None


def test_case_deletion_ui_is_explicit_and_does_not_use_browser_storage():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "case_deletion.js").read_text(encoding="utf-8")
    assert "/demo/case_deletion.js" in loader
    assert "mcr-case-deletion" in loader
    assert "Escribe ELIMINAR para confirmar" in script
    assert "confirmation: 'DELETE'" in script
    assert "method: 'DELETE'" in script
    assert "Eliminar este expediente" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_case_deletion_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "case_deletion.js"]:
        script = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
