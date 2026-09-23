from pathlib import Path
import shutil
import subprocess


def _quality_js() -> str:
    return (Path(__file__).parents[1] / "app" / "static" / "dossier_quality.js").read_text(
        encoding="utf-8"
    )


def test_product_home_loads_dossier_quality_layer(client):
    response = client.get("/")
    assert response.status_code == 200
    assert '<script src="/demo/dossier_quality.js"></script>' in response.text


def test_demo_entrypoints_load_guarded_product_layer(client):
    for path in ("/demo/", "/demo/index.html"):
        response = client.get(path)
        assert response.status_code == 200
        assert '<script src="/demo/dossier_quality.js"></script>' in response.text
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        # The unresolved placeholder is replaced with the reviewed first
        # layer, or with nothing while business/legal details are incomplete.
        assert '<div id="mcr-privacy-layer"></div>' not in response.text


def test_quality_layer_explains_evidence_not_success_score():
    script = _quality_js()
    assert "/api/cases/${caseId}/quality" in script
    assert "Hechos críticos confirmados" in script
    assert "Hechos con apoyo documental" in script
    assert "Revisiones humanas abiertas" in script
    assert "No es una probabilidad de éxito jurídico" in script
    assert "%" not in script


def test_quality_layer_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    path = Path(__file__).parents[1] / "app" / "static" / "dossier_quality.js"
    result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
