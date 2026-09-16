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
    RESOLVED_PENDING_EXECUTION: {
      title: 'Pendiente de comprobar el cumplimiento',
      detail: 'La empresa ha aceptado, pero el expediente no se cierra hasta verificar qué se ha cumplido realmente.'
    },
    RESOLVED: {
      title: 'Expediente resuelto',
      detail: 'El resultado ya está registrado como cumplido. Los hechos iniciales quedan cerrados para conservar la trazabilidad.'
    },
  };

  function applyPhaseGuard() {
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
