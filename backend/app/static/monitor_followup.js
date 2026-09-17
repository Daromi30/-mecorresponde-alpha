(() => {
  function currentAction() {
    if (!caseData?.current_action_id || !Array.isArray(caseData.actions)) return null;
    return caseData.actions.find(item => item.id === caseData.current_action_id) || null;
  }

  function renderMonitorFollowup() {
    if (!caseId || caseData?.status !== 'DIAGNOSED') return;
    const current = currentAction();
    if (!current?.type?.startsWith('MONITOR_')) return;

    const card = document.getElementById('caseNextStep');
    if (!card) return;
    card.classList.remove('hidden');
    card.innerHTML = `
      <div class="label">Qué hago ahora</div>
      <h3 style="margin:6px 0">Actualiza el expediente si la situación cambia</h3>
      <p class="muted" style="margin:0">El Motor no propone una reclamación nueva mientras la situación siga igual. Si aparece el hecho que estamos vigilando, confírmalo aquí para volver a analizar el caso sin empezar de cero.</p>
      <div class="actions"><button type="button" id="caseMonitorFollowup">Actualizar si ha cambiado</button></div>`;
    document.getElementById('caseMonitorFollowup')?.addEventListener('click', () => {
      document.getElementById('questionArea')?.scrollIntoView({behavior: 'smooth', block: 'center'});
    });
  }

  const baseRefresh = refresh;
  refresh = async function (...args) {
    const result = await baseRefresh(...args);
    renderMonitorFollowup();
    return result;
  };
})();
