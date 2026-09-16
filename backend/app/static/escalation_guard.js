(() => {
  function currentAction() {
    if (!caseData?.current_action_id) return null;
    return (caseData.actions || []).find(action => action.id === caseData.current_action_id) || null;
  }

  function applyEscalationGuard() {
    const action = currentAction();
    if (caseData?.status !== 'HUMAN_REVIEW' || action?.type !== 'HUMAN_REVIEW') return;

    const actions = document.getElementById('diagnosisActions');
    if (!actions) return;

    if (action?.payload?.phase === 'POST_RESPONSE_ESCALATION') {
      actions.innerHTML = `
        <div class="notice">
          <b>La empresa ha respondido y el expediente necesita decidir el siguiente escalado.</b><br>
          No voy a repetir la reclamación inicial ni a inventar un organismo, plazo o vía jurídica. El siguiente paso queda detenido hasta revisión del expediente.
        </div>`;
      return;
    }

    if (action?.payload?.phase === 'PROFESSIONAL_REVIEW') {
      actions.innerHTML = `
        <div class="notice">
          <b>El expediente está en revisión profesional.</b><br>
          El Motor automático se ha detenido porque el siguiente paso requiere criterio jurídico humano. No se ha generado automáticamente ningún organismo, vía, plazo, remedio ni probabilidad de éxito.
        </div>`;
    }
  }

  const baseRenderDecision = renderDecision;
  renderDecision = function (...args) {
    const result = baseRenderDecision(...args);
    applyEscalationGuard();
    return result;
  };

  const baseRefresh = refresh;
  refresh = async function (...args) {
    const result = await baseRefresh(...args);
    applyEscalationGuard();
    return result;
  };
})();
