(() => {
  const stages = [
    {key: 'understand', label: 'Entender', detail: 'Problema y hechos'},
    {key: 'diagnose', label: 'Comprobar', detail: '¿Me corresponde?'},
    {key: 'act', label: 'Actuar', detail: 'Preparar y enviar'},
    {key: 'response', label: 'Respuesta', detail: 'Analizar y escalar'},
    {key: 'resolve', label: 'Resolver', detail: 'Verificar resultado'},
  ];

  const stageByStatus = {
    INTAKE: 0,
    NEEDS_INFORMATION: 0,
    DIAGNOSED: 1,
    READY_TO_SUBMIT: 2,
    WAITING_RESPONSE: 3,
    RESPONSE_RECEIVED: 3,
    RESOLVED_PENDING_EXECUTION: 4,
    RESOLVED: 4,
    CLOSED_UNSUPPORTED: 0,
  };

  function hasAction(type) {
    return Array.isArray(caseData?.actions) && caseData.actions.some(action => action?.type === type);
  }

  function reviewStage() {
    // A review may happen before any legal diagnosis (unsupported intake), after diagnosis
    // but before a claim is sent, or after a company response. Never move the progress bar
    // forward merely because the status string says HUMAN_REVIEW/REANALYZING.
    if (hasAction('WAIT_FOR_RESPONSE') || hasAction('VERIFY_EXECUTION')) return 3;
    if (caseData?.current_decision_id && Array.isArray(caseData.decisions) && caseData.decisions.some(item => item.id === caseData.current_decision_id)) return 1;
    if (caseData?.family) return 1;
    return 0;
  }

  function stageForStatus(status) {
    if (status === 'DIAGNOSED' && (!caseData?.current_decision_id || !Array.isArray(caseData.decisions) || !caseData.decisions.some(item => item.id === caseData.current_decision_id))) return 0;
    if (status === 'HUMAN_REVIEW' || status === 'REANALYZING') return reviewStage();
    return stageByStatus[status] ?? 0;
  }

  function ensureProgress() {
    let panel = document.getElementById('caseProgress');
    if (panel) return panel;
    const header = document.querySelector('#workspace .caseHeader');
    if (!header) return null;
    panel = document.createElement('div');
    panel.id = 'caseProgress';
    panel.className = 'panel';
    panel.style.padding = '16px';
    panel.style.marginTop = '0';
    header.insertAdjacentElement('afterend', panel);
    return panel;
  }

  function statusCopy(status) {
    return ({
      INTAKE: 'Estamos separando hechos confirmados de lo que todavía falta.',
      NEEDS_INFORMATION: 'Necesitamos un dato más antes de poder aplicar las reglas con seguridad.',
      DIAGNOSED: 'Ya hay un diagnóstico basado en las reglas y hechos actuales.',
      READY_TO_SUBMIT: 'La siguiente acción está preparada; revisa el contenido antes de enviarlo.',
      WAITING_RESPONSE: 'La reclamación consta como enviada. El siguiente paso depende de la respuesta real.',
      RESPONSE_RECEIVED: 'La respuesta de la empresa ya forma parte del expediente y está siendo tratada.',
      HUMAN_REVIEW: 'El Motor se ha detenido porque este punto necesita revisión humana antes de continuar.',
      REANALYZING: 'Se han incorporado nuevos hechos y el Motor está recalculando el siguiente paso.',
      RESOLVED_PENDING_EXECUTION: 'La empresa ha aceptado algo, pero todavía falta comprobar que lo haya cumplido.',
      RESOLVED: 'La resolución se ha verificado con el resultado registrado en el expediente.',
      CLOSED_UNSUPPORTED: 'Este caso no está automatizado todavía y no se va a forzar una respuesta.',
    })[status] || 'El expediente sigue avanzando por el Motor de Resolución.';
  }

  function renderProgress() {
    if (!caseId || !caseData) return;
    const panel = ensureProgress();
    if (!panel) return;
    const status = caseData.status || 'INTAKE';
    const current = stageForStatus(status);
    const resolved = status === 'RESOLVED';
    const diagnosedWithoutPendingAction = status === 'DIAGNOSED' && !!caseData.current_decision_id && !caseData.current_action_id;
    panel.classList.remove('hidden');
    panel.innerHTML = `
      <div class="label">Dónde estás</div>
      <div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px;margin:10px 0 12px" aria-label="Progreso del expediente">
        ${stages.map((stage, index) => {
          const done = index < current || (resolved && index <= current) || (diagnosedWithoutPendingAction && index <= current);
          const active = index === current && !resolved && !diagnosedWithoutPendingAction;
          const background = done ? '#e9f5ed' : active ? '#dfeae2' : '#f5f6f2';
          const border = done || active ? '#aac8b4' : '#e2e4dd';
          const marker = done ? '✓' : String(index + 1);
          return `<div style="border:1px solid ${border};background:${background};border-radius:12px;padding:9px;min-width:0" data-progress-stage="${stage.key}" data-progress-state="${done ? 'done' : active ? 'active' : 'pending'}">
            <div style="font-size:12px;font-weight:900">${marker} ${escapeHtml(stage.label)}</div>
            <div class="tiny muted" style="margin-top:2px">${escapeHtml(stage.detail)}</div>
          </div>`;
        }).join('')}
      </div>
      <div class="tiny muted">${escapeHtml(status === 'DIAGNOSED' && current === 0 ? 'No hay un diagnóstico vigente verificable.' : statusCopy(status))}</div>`;
  }

  const baseRefresh = refresh;
  refresh = async function (...args) {
    const result = await baseRefresh(...args);
    renderProgress();
    return result;
  };

  const baseNewCase = newCase;
  newCase = function (...args) {
    const result = baseNewCase(...args);
    const panel = document.getElementById('caseProgress');
    if (panel) panel.classList.add('hidden');
    return result;
  };
})();
