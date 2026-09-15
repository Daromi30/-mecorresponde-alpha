from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"
PASSWORD = "strong-password-for-export"


def register(client, email="export@example.com"):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"]


def create_and_claim(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    claimed = client.post(f"/api/cases/{case_id}/claim")
    assert claimed.status_code == 200, claimed.text
    return case_id


def test_account_export_requires_authenticated_account(client):
    response = client.get("/api/auth/export")
    assert response.status_code == 401


def test_account_export_contains_owned_case_data_without_authentication_secrets(client):
    user_id = register(client)
    case_id = create_and_claim(client)
    fact = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": "electricity.billing.synthetic_note",
            "value": "dato de prueba",
            "state": "confirmed",
            "user_confirmed": True,
        },
    )
    assert fact.status_code == 200, fact.text

    response = client.get("/api/auth/export")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    body = response.json()

    assert body["export_version"] == 1
    assert body["scope"] == "structured_account_and_owned_case_data"
    assert body["document_files_included"] is False
    assert body["account"]["id"] == user_id
    assert body["account"]["email"] == "export@example.com"
    assert len(body["cases"]) == 1
    assert body["cases"][0]["id"] == case_id
    assert any(
        item["key"] == "electricity.billing.synthetic_note" and item["value"] == "dato de prueba"
        for item in body["cases"][0]["facts"]
    )

    serialized = response.text.lower()
    assert "password_hash" not in serialized
    assert "token_hash" not in serialized
    assert "storage_key" not in serialized
    assert PASSWORD.lower() not in serialized


def test_account_export_does_not_include_another_users_case(client):
    register(client, "first@example.com")
    first_case = create_and_claim(client)
    assert client.post("/api/auth/logout").status_code == 200

    register(client, "second@example.com")
    second_case = create_and_claim(client)
    body = client.get("/api/auth/export").json()
    ids = {case["id"] for case in body["cases"]}
    assert second_case in ids
    assert first_case not in ids


def test_account_export_ui_is_loaded_and_describes_structured_copy_only():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "account_export.js").read_text(encoding="utf-8")
    assert "/demo/account_export.js" in loader
    assert "mcr-account-export" in loader
    assert "/api/auth/export" in script
    assert "Descargar copia de mis datos" in script
    assert "Los archivos originales adjuntos no se incrustan" in script
    assert "password" not in script.lower()
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_account_export_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "account_export.js"]:
        script = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
