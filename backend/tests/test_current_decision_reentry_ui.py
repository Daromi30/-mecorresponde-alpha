from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def test_refresh_and_reentry_never_promote_historical_decision():
    node = shutil.which("node")
    if not node:
        return
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    inline = html.split("<script>", 1)[1].split("</script>", 1)[0]
    inline = inline.split("$('accountDialog').addEventListener", 1)[0]
    next_step = (STATIC / "case_next_step.js").read_text(encoding="utf-8")
    progress = (STATIC / "case_progress.js").read_text(encoding="utf-8")
    phase_guard = (STATIC / "case_phase_guard.js").read_text(encoding="utf-8")
    harness = r"""
const elements = {};
function el(id) {
  if (!elements[id]) {
    const classes = new Set(['hidden']);
    elements[id] = {
      id, innerHTML:'', textContent:'', style:{}, dataset:{}, value:'', children:[],
      classList:{add:c=>classes.add(c), remove:c=>classes.delete(c), contains:c=>classes.has(c), toggle:(c,on)=>on?classes.add(c):classes.delete(c)},
      insertAdjacentElement:(_where,child)=>{elements[child.id]=child},
      listeners:{}, addEventListener:function(event,callback){this.listeners[event]=callback},
      reportValidity:()=>true, scrollIntoView:()=>{}, focus:()=>{},
    };
  }
  return elements[id];
}
global.document = {
  getElementById:el,
  querySelector:selector=>selector==='#workspace .caseHeader'?el('header'):null,
  createElement:()=>el('new-'+Math.random()),
};
global.window = {scrollTo:()=>{}};
"""
    checks = r"""
caseId='c02';
renderAccountState=()=>{};
const old={id:'A',viability:'LOW',claimable_amount:999,reasoning_summary:'HISTORICO_MONITOR',rule_evaluations:[{rule_id:'OLD_RULE'}]};
const now={id:'B',viability:'HIGH',claimable_amount:20,reasoning_summary:'VIGENTE_NUEVO',rule_evaluations:[{rule_id:'NEW_RULE'}]};
let snapshot={id:'c02',status:'DIAGNOSED',family:'C02',current_decision_id:'A',current_action_id:null,decisions:[old],actions:[],facts:[]};
let correctionRequest=null;
req=async (path,options)=>{
  if(path.endsWith('/next-question'))return {done:true};
  if(options?.method==='POST'){
    correctionRequest=JSON.parse(options.body);
    snapshot={...snapshot,status:'INTAKE',current_decision_id:null,facts:[...snapshot.facts,{id:'f2',key:'electricity.billing.correct_amount',value:80,state:'confirmed',user_confirmed:true}]};
    return {fact_id:'f2'};
  }
  return snapshot;
};
function assert(condition, message){if(!condition)throw new Error(message)}
async function check(){
  await refresh();
  assert(!el('diagnosisCard').classList.contains('hidden'),'initial active decision absent');
  assert(el('diagnosis').innerHTML.includes('HISTORICO_MONITOR'),'initial diagnosis absent');
  snapshot={...snapshot,status:'INTAKE',current_decision_id:null};
  await refresh();
  assert(el('diagnosisCard').classList.contains('hidden'),'old diagnosis visible after C02 fact change');
  assert(!el('diagnosis').innerHTML.includes('HISTORICO_MONITOR'),'old diagnosis content retained');
  assert(el('caseNextStep').innerHTML.includes('Completa el dato que falta'),'intake guidance absent');
  await refresh(); // reentry/refresh of the same persisted snapshot
  assert(el('diagnosisCard').classList.contains('hidden'),'old diagnosis visible after reentry');
  snapshot={...snapshot,status:'DIAGNOSED',current_decision_id:'missing'};
  await refresh();
  assert(el('diagnosisCard').classList.contains('hidden'),'invalid current id fell back to history');
  assert(!el('caseNextStep').innerHTML.includes('Análisis concluido'),'invalid current id yielded current recommendation');
  snapshot={...snapshot,current_decision_id:'B',decisions:[old,now]};
  await refresh();
  assert(el('diagnosis').innerHTML.includes('VIGENTE_NUEVO'),'current B absent');
  assert(!el('diagnosis').innerHTML.includes('HISTORICO_MONITOR'),'historical A shown instead of B');
  snapshot={...snapshot,current_decision_id:null};
  await refresh();
  assert(el('diagnosisCard').classList.contains('hidden'),'null current id fell back to first decision');
  snapshot={...snapshot,status:'READY_TO_SUBMIT',current_decision_id:'missing',current_action_id:'a1',actions:[{id:'a1',type:'SUBMIT_INITIAL_CLAIM',status:'READY',payload:{text:'STALE_CLAIM'}}]};
  await refresh();
  assert(el('claimCard').classList.contains('hidden'),'stale prepared claim visible without current decision');
  assert(!el('caseNextStep').innerHTML.includes('Abrir acción preparada'),'stale next action offered');
  // E02-A informational diagnosis: visible correction edits this case, not a new one.
  caseId='e02';
  snapshot={id:'e02',status:'DIAGNOSED',family:'E02-A',current_decision_id:'B',current_action_id:null,
    decisions:[now],actions:[],facts:[{id:'f1',key:'electricity.billing.correct_amount',value:100,state:'confirmed',user_confirmed:true,created_by:'user'}]};
  await refresh();
  assert(el('caseNextStep').innerHTML.includes('Corregir datos'),'correction control absent');
  el('caseCorrectFact').listeners.click();
  el('correctAmount').value='80';
  await el('saveCorrectAmount').listeners.click();
  assert(correctionRequest.correction===true && correctionRequest.value===80,'UI did not submit validated correction');
  assert(caseId==='e02' && snapshot.id==='e02','correction created/switched case');
  assert(el('diagnosisCard').classList.contains('hidden'),'old E02 conclusion still visible');
  await refresh();
  assert(el('diagnosisCard').classList.contains('hidden'),'old E02 conclusion visible after reentry');
}
check().catch(error=>{console.error(error);process.exit(1)});
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(harness + inline + "\n" + next_step + "\n" + progress + "\n" + phase_guard + "\n" + checks)
        script = handle.name
    result = subprocess.run([node, script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
