from pathlib import Path
import json
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_product_loads_resolution_progress_tracker():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "case_progress.js").read_text(encoding="utf-8")
    assert "/demo/case_progress.js" in loader
    assert "mcr-case-progress" in loader
    assert "Dónde estás" in script
    assert "Entender" in script
    assert "Comprobar" in script
    assert "Actuar" in script
    assert "Respuesta" in script
    assert "Resolver" in script


def test_progress_covers_resolution_lifecycle_without_success_probability():
    script = (STATIC / "case_progress.js").read_text(encoding="utf-8")
    for status in [
        "INTAKE",
        "NEEDS_INFORMATION",
        "DIAGNOSED",
        "READY_TO_SUBMIT",
        "WAITING_RESPONSE",
        "RESPONSE_RECEIVED",
        "HUMAN_REVIEW",
        "REANALYZING",
        "RESOLVED_PENDING_EXECUTION",
        "RESOLVED",
        "CLOSED_UNSUPPORTED",
    ]:
        assert status in script
    assert "WAIT_FOR_RESPONSE" in script
    lowered = script.lower()
    assert "probabilidad de éxito" not in lowered
    assert "porcentaje de éxito" not in lowered


def test_human_review_progress_uses_real_case_history_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return

    source = (STATIC / "case_progress.js").read_text(encoding="utf-8")
    harness = f"""
let caseId = 'case-1';
let caseData = null;
const elements = {{}};
const header = {{
  insertAdjacentElement: (_where, el) => {{ elements[el.id] = el; }}
}};
function fakeElement() {{
  return {{
    id: '',
    className: '',
    style: {{}},
    innerHTML: '',
    classList: {{ add: () => {{}}, remove: () => {{}} }},
  }};
}}
global.document = {{
  getElementById: id => elements[id] || null,
  querySelector: selector => selector === '#workspace .caseHeader' ? header : null,
  createElement: () => fakeElement(),
}};
global.escapeHtml = value => String(value ?? '');
let refresh = async () => null;
let newCase = () => null;
{source}
async function activeStage(data) {{
  caseData = data;
  await refresh();
  const html = elements.caseProgress.innerHTML;
  const match = html.match(/data-progress-stage=\"([^\"]+)\" data-progress-state=\"active\"/);
  if (!match) throw new Error('No active progress stage: ' + html);
  return match[1];
}}
(async () => {{
  const stages = [];
  stages.push(await activeStage({{status:'HUMAN_REVIEW', family:null, decisions:[], actions:[]}}));
  stages.push(await activeStage({{status:'HUMAN_REVIEW', family:'E06', decisions:[{{id:'d1'}}], actions:[{{type:'HUMAN_REVIEW_METER_TECHNICAL'}}]}}));
  stages.push(await activeStage({{status:'HUMAN_REVIEW', family:'E04-B', decisions:[{{id:'d2'}}], actions:[{{type:'WAIT_FOR_RESPONSE', status:'COMPLETED'}}, {{type:'HUMAN_REVIEW'}}]}}));
  console.log(JSON.stringify(stages));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    result = subprocess.run([node, "-e", harness], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip()) == ["understand", "diagnose", "response"]


def test_case_progress_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "case_progress.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
