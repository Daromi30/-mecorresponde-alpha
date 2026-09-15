from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_alpha_product_loads_synthetic_data_guardrail():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "alpha_data_guardrail.js").read_text(encoding="utf-8")
    assert "/demo/alpha_data_guardrail.js" in loader
    assert "mcr-alpha-data-guardrail" in loader
    assert "usa solo datos ficticios" in script
    assert "DNI/NIE" in script
    assert "emails reales" in script
    assert "documentos reales" in script
    assert "beta con datos personales seguirá bloqueada" in script
    assert "email ficticio" in script


def test_alpha_guardrail_does_not_claim_privacy_compliance():
    script = (STATIC / "alpha_data_guardrail.js").read_text(encoding="utf-8").lower()
    assert "cumplimiento" not in script
    assert "rgpd" not in script
    assert "gdpr" not in script


def test_alpha_guardrail_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename in ["dossier_quality.js", "alpha_data_guardrail.js"]:
        script = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"
