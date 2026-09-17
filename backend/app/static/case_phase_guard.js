(() => {
  const lockedPhaseCopy = {
    WAITING_RESPONSE: {
      title: 'Reclamación enviada',
      detail: 'Los hechos y la reclamación inicial quedan bloqueados mientras esperamos una respuesta. Registra la respuesta real cuando llegue.'
    },
    RESPONSE_RECEIVED: {
      title: 'Respuesta incorporada',
      detail: 'La fase inicial ya está cerrada. El expediente continúa con el análisis de la respuesta y, si hace falta, con el escalado.'
    },
    HUMAN_REVIEW: {
      title: 'Expediente en revisión',
      detail: 'No se puede reabrir la fase inicial mientras exista una revisión humana pendiente.'
    },
    REANALYZING: {
      title: 'Reanalizando el expediente',
      detail: 'Se han incorporado hechos revisados y el Motor está recalculando el siguiente paso. No edites la fase inicial mientras termina esta transición.'
    },
    RESOLVED_PENDING_EXECUTION: {
      title: 'Pendiente de comprobar el cumplimiento',
      detail: 'La empresa ha aceptado, pero el expediente no se cierra hasta verificar qué se ha cumplido realmente.'
    },
    RESOLVED: {
      title: 'Expediente resuelto',
      detail: 'El resultado ya está registrado como cumplido. Los hechos iniciales quedan cerrados para conservar la trazabilidad.'
    },
    CLOSED_UNSUPPORTED: {
      title: 'Expediente cerrado fuera del alcance automatizado',
      detail: 'Este expediente quedó cerrado sin una resolución automatizada aplicable. Los hechos iniciales permanecen bloqueados para conservar la trazabilidad del cierre.'
    },
  };

  function currentAction() {
    if (!caseData?.current_action_id) return null;
    return (caseData.actions || []).find(action => action.id === caseData.current_action_id) || null;
  }

  function setCardVisible(id, visible) {
    const card = document.getElementById(id);
    if (!card) return;
    card.classList.toggle('hidden', !visible);
  }

  function restorePreparedClaim() {
    if (caseData?.status !== 'READY_TO_SUBMIT') return;
    const action = currentAction();
    if (
      action?.type !== 'SUBMIT_INITIAL_CLAIM' ||
      action?.status !== 'READY' ||
      !action?.payload ||
      typeof renderClaim !== 'function'
    ) return;
    renderClaim(action.payload);
  }

  function applyActionVisibility() {
    const status = caseData?.status || 'INTAKE';

    // A card is actionable only in its exact lifecycle phase. This prevents stale
    // controls from remaining visible after refreshes and producing predictable 409s.
    setCardVisible('claimCard', status === 'READY_TO_SUBMIT');
    setCardVisible('responseCard', status === 'WAITING_RESPONSE');
    setCardVisible('outcomeCard', status === 'RESOLVED_PENDING_EXECUTION');

    // READY_TO_SUBMIT must survive login/re-entry without asking the user to
    // "prepare" an already prepared action again. The persisted current action
    // contains the exact claim payload and legal provenance produced by the Motor.
    restorePreparedClaim();
  }

  function applyPhaseGuard() {
    applyActionVisibility();
    const copy = lockedPhaseCopy[caseData?.status];
    if (!copy) return;
    const area = document.getElementById('questionArea');
    if (!area) return;
    area.innerHTML = `
      <div class="notice">
        <b>${escapeHtml(copy.title)}</b><br>
        ${escapeHtml(copy.detail)}
      </div>`;
  }

  const baseRefresh = refresh;
  refresh = async function (...args) {
    const result = await baseRefresh(...args);
    applyPhaseGuard();
    return result;
  };
})();
