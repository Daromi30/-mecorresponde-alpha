from pathlib import Path
import re
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"
LOAD_PATTERN = re.compile(r"loadEnhancement\('/demo/([^']+)', '([^']+)'\);")


def _enhancements():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    return LOAD_PATTERN.findall(loader)


def test_every_declared_consumer_enhancement_exists_and_has_unique_loader_key():
    enhancements = _enhancements()
    assert enhancements
    filenames = [filename for filename, _ in enhancements]
    dataset_keys = [dataset_key for _, dataset_key in enhancements]
    assert len(filenames) == len(set(filenames))
    assert len(dataset_keys) == len(set(dataset_keys))
    missing = [filename for filename in filenames if not (STATIC / filename).is_file()]
    assert missing == []


def test_every_declared_consumer_enhancement_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    for filename, _ in _enhancements():
        script = (STATIC / filename).read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"{filename}: {result.stderr}"


def test_lifecycle_enhancements_load_in_fail_safe_order():
    filenames = [filename for filename, _ in _enhancements()]
    required_order = [
        "guided_question_inputs.js",
        "submission_evidence.js",
        "response_evidence.js",
        "outcome_evidence.js",
        "escalation_guard.js",
        "case_phase_guard.js",
        "case_progress.js",
        "case_next_step.js",
    ]
    indexes = [filenames.index(filename) for filename in required_order]
    assert indexes == sorted(indexes)
