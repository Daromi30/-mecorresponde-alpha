from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_product_enhancement_layer_loads_documentation_module():
    quality = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    assert "/demo/documentation.js" in quality
    assert "mcr-documentation" in quality
    assert "/demo/deadline_guidance.js" in quality


def test_documentation_ui_fails_closed_when_persistent_storage_is_unavailable():
    script = (STATIC / "documentation.js").read_text(encoding="utf-8")
    assert "/health/storage" in script
    assert "if (!status.uploads_allowed)" in script
    assert "no aceptará documentos hasta disponer de almacenamiento persistente" in script
    assert "No se ha enviado ni guardado ningún archivo" in script


def test_document_upload_uses_multipart_and_does_not_auto_confirm_extraction():
    script = (STATIC / "documentation.js").read_text(encoding="utf-8")
    assert "new FormData()" in script
    assert "/documents`" in script
    assert "Los datos extraídos no se convierten en hechos confirmados automáticamente" in script
    assert "confirm-fact" not in script
    assert "Content-Type" not in script


def test_documentation_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "documentation.js"]:
        script = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
