from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_product_home_loads_account_deletion_module(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "/demo/dossier_quality.js" in response.text

    quality = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    assert "/demo/account_deletion.js" in quality
    assert "data-mcr-account-deletion" in quality


def test_account_deletion_ui_requires_password_and_explicit_confirmation():
    script = (STATIC / "account_deletion.js").read_text(encoding="utf-8")
    assert "Eliminar mi cuenta y expedientes" in script
    assert "Escribe ELIMINAR para confirmar" in script
    assert "autocomplete=\"current-password\"" in script
    assert "confirmation: 'DELETE'" in script
    assert "method: 'DELETE'" in script
    assert "/api/auth/account" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_account_deletion_ui_does_not_claim_regulatory_compliance():
    script = (STATIC / "account_deletion.js").read_text(encoding="utf-8").lower()
    assert "rgpd" not in script
    assert "gdpr" not in script
    assert "cumplimiento" not in script


def test_account_deletion_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "account_deletion.js"]:
        script = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
