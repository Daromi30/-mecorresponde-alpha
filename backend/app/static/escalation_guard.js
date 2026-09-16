(() => {
  function currentAction() {
    if (!caseData?.current_action_id) return null;
    return (caseData.actions || []).find(action => action.id === caseData.current_action_id) || null;
  }

  function applyEscalationGuard() {
    const action = currentAction();
    if (
      caseData?.status !== 'HUMAN_REVIEW' ||
      action?.type !== 'HUMAN_REVIEW' ||
      action?.payload?.phase !== 'POST_RESPONSE_ESCALATION'
    ) return;

    const actions = document.getElementById('diagnosisActions');
    if (!actions) return;
    actions.innerHTML = `
      <div class="notice">
        <b>La empresa ha respondido y el expediente necesita decidir el siguiente escalado.</b><br>
        No voy a repetir la reclamación inicial ni a inventar un organismo, plazo o vía jurídica. El siguiente paso queda detenido hasta revisión del expediente.
      </div>`;
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
