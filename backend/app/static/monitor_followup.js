(() => {
  function currentAction() {
    if (!caseData?.current_action_id || !Array.isArray(caseData.actions)) return null;
    return caseData.actions.find(item => item.id === caseData.current_action_id) || null;
  }

  function followupCopy(type) {
    if (type?.startsWith('MONITOR_')) {
      return {
        title: 'Actualiza el expediente si la situación cambia',
        body: 'El Motor no propone una reclamación nueva mientras la situación siga igual. Si aparece el hecho que estamos vigilando, confírmalo aquí para volver a analizar el caso sin empezar de cero.',
        button: 'Actualizar si ha cambiado',
      };
    }
    if (type === 'CHECK_BILL_AGAINST_REAL_READING') {
      return {
        title: 'Compara la factura con la lectura real',
        body: 'Ya consta una lectura real. Comprueba si el consumo facturado coincide con ella y registra únicamente el resultado de esa comparación. Si no coincide, el Motor trasladará el análisis monetario a facturación.',
        button: 'Registrar comparación',
      };
    }
    return null;
  }

  function renderExternalFollowup() {
    if (!caseId || caseData?.status !== 'DIAGNOSED') return;
    const current = currentAction();
    const copy = followupCopy(current?.type || '');
    if (!copy) return;

    const card = document.getElementById('caseNextStep');
    if (!card) return;
    card.classList.remove('hidden');
    card.innerHTML = `
      <div class="label">Qué hago ahora</div>
      <h3 style="margin:6px 0">${escapeHtml(copy.title)}</h3>
      <p class="muted" style="margin:0">${escapeHtml(copy.body)}</p>
      <div class="actions"><button type="button" id="caseExternalFollowup">${escapeHtml(copy.button)}</button></div>`;
    document.getElementById('caseExternalFollowup')?.addEventListener('click', () => {
      document.getElementById('questionArea')?.scrollIntoView({behavior: 'smooth', block: 'center'});
    });
  }

  const baseRefresh = refresh;
  refresh = async function (...args) {
    const result = await baseRefresh(...args);
    renderExternalFollowup();
    return result;
  };
})();
