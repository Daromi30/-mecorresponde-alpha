from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_claimant_diagnosis_hides_internal_codes_but_keeps_history_explicit():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    render = html.split("function renderDecision(d)", 1)[1].split("function renderFullDiagnosis", 1)[0]

    assert "OUT_OF_SCOPE:'Fuera del alcance automatizado'" in html
    assert "PRICE_REDUCTION_REQUIRES_PROPORTIONAL_VALUATION:'La rebaja del precio requiere valorar la proporción'" in html
    assert "PRESUMPTION_MAY_BE_INCOMPATIBLE_WITH_NATURE_OR_DEFECT:'La naturaleza del producto o del defecto podría afectar a la presunción'" in html
    assert "SELLER_REFUSED_CONFORMITY:'El vendedor se negó a poner el producto en conformidad'" in html
    assert "confirmed:'Confirmado según los datos declarados'" in html
    assert "potential:'Posible, requiere comprobación'" in html
    assert "Aspectos que pueden influir en la reclamación" in render
    assert "Qué podría tumbar la reclamación" not in render
    assert "counterargumentLabel(x.type)" in render
    assert "counterargumentStatusLabel(x.status)" in render
    assert "ruleResultLabel(r.result)" in render
    assert "r.rule_id" not in render
    assert "Diagnóstico previo · consulta el estado actual" in render
    assert "Importe calculado en el diagnóstico previo" in render
    assert "other_urban_use:'Otro uso urbano'" in html
    assert "tourist_or_hospitality:'Alquiler turístico u hospedaje'" in html
    assert "statutory_cash_deposit:'Fianza legal en metálico'" in html
    assert "deductions_or_amount_disputed:'Hay descuentos o se discute el importe'" in html
    assert "escapeHtml(choiceLabel(o))" in html


def test_claimant_inline_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_loaded_guided_question_module_uses_human_choice_labels():
    node = shutil.which("node")
    if not node:
        return
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    choice = "function choiceLabel(o)" + html.split("function choiceLabel(o)", 1)[1].split("\n", 1)[0]
    module = (STATIC / "guided_question_inputs.js").read_text(encoding="utf-8")
    harness = """
const escapeHtml = value => String(value);
let inputFor = () => '';
let renderQuestion = () => {};
let answer = () => {};
let addChargeRow = () => {};
let saveCharges = () => {};
global.window = {};
"""
    checks = """
const html = inputFor({input_type:'choice', options:[
  {value:'dwelling',label:'dwelling'},
  {value:'other_urban_use',label:'other urban use'},
  {value:'statutory_cash_deposit',label:'statutory cash deposit'},
  {value:'deductions_or_amount_disputed',label:'deductions or amount disputed'},
]});
if (!html.includes('Vivienda') || !html.includes('Otro uso urbano')) process.exit(1);
if (!html.includes('Fianza legal en metálico') || !html.includes('Hay descuentos o se discute el importe')) process.exit(4);
if (!html.includes('value="dwelling"') || !html.includes('value="other_urban_use"')) process.exit(2);
if (!html.includes('value="statutory_cash_deposit"') || !html.includes('value="deductions_or_amount_disputed"')) process.exit(5);
if (html.includes('>dwelling<') || html.includes('>other urban use<')) process.exit(3);
"""
    result = subprocess.run(
        [node, "-e", harness + choice + "\n" + module + "\n" + checks],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
