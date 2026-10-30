"""RB-031 dependency reproducibility and fail-closed regression tests."""

import io
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from app.config import Settings


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def test_lock_covers_direct_dependencies_with_exact_versions_and_hashes():
    source = (BACKEND_ROOT / "requirements.txt").read_text(encoding="utf-8")
    lock = (BACKEND_ROOT / "requirements.lock").read_text(encoding="utf-8")
    direct = {
        _canonical(re.split(r"[<>=!\[]", line, maxsplit=1)[0])
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    blocks = re.split(r"(?m)(?=^[A-Za-z0-9][A-Za-z0-9_.-]*==)", lock)
    packages = set()
    for block in blocks[1:]:
        first_line = block.splitlines()[0]
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==[^\s\\]+ \\$", first_line)
        assert match, first_line
        assert re.search(r"(?m)^    --hash=sha256:[0-9a-f]{64}", block), first_line
        packages.add(_canonical(match.group(1)))

    assert direct <= packages
    assert "--index-url" not in lock
    assert "--trusted-host" not in lock
    assert "pypdf==6.21.4" in lock


def test_ci_and_render_install_only_the_hashed_lock_and_actions_are_sha_pinned():
    workflow_texts = [
        path.read_text(encoding="utf-8")
        for path in sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml"))
    ]
    combined = "\n".join(workflow_texts)
    action_refs = re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", combined)
    assert action_refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)
    assert "cache-dependency-path: backend/requirements.lock" in combined
    assert combined.count("--require-hashes -r requirements.lock") == 4
    assert "pip install -r requirements.txt" not in combined
    assert combined.count("python -m pip check") == 4

    render = (REPOSITORY_ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "--require-hashes -r requirements.lock" in render
    assert "python -m pip check" in render
    assert "plan: free" in render


def test_dependency_change_does_not_open_runtime_controls():
    defaults = {name: field.default for name, field in Settings.model_fields.items()}
    assert defaults["document_storage_backend"] == "local"
    assert defaults["document_storage_persistent"] is False
    assert defaults["admin_api_token"] == ""
    assert defaults["email_delivery_provider"] == "disabled"
    assert defaults["privacy_information_reviewed"] is False
    assert defaults["public_indexing_enabled"] is False
    assert defaults["real_beta_enabled"] == "false"
    assert defaults["real_beta_allowlist"] == ""


def test_pypdf_security_upgrade_preserves_reader_writer_compatibility():
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    output.seek(0)
    reader = PdfReader(output)
    assert len(reader.pages) == 1
