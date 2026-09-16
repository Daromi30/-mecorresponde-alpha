(() => {
  function ensurePanel() {
    let panel = document.getElementById('caseHandoffCard');
    if (panel) return panel;
    const workspace = document.getElementById('workspace');
    if (!workspace) return null;

    panel = document.createElement('div');
    panel.id = 'caseHandoffCard';
    panel.className = 'panel hidden';
    panel.innerHTML = `
      <div class="label">Expediente para revisión</div>
      <p class="muted">Prepara una copia estructurada de este caso con hechos, trazabilidad, comunicaciones y las versiones exactas de las fuentes jurídicas que ha evaluado el Motor. No incluye contraseñas, tokens, logs internos ni claves de almacenamiento.</p>
      <button type="button" class="secondary" id="downloadCaseHandoff">Descargar expediente estructurado</button>
      <div id="caseHandoffStatus"></div>`;
    workspace.appendChild(panel);

    const button = panel.querySelector('#downloadCaseHandoff');
    const status = panel.querySelector('#caseHandoffStatus');
    button.addEventListener('click', async () => {
      if (!caseId) return;
      const previous = button.textContent;
      button.disabled = true;
      button.textContent = 'Preparando expediente…';
      status.innerHTML = '';
      try {
        const data = await req(`/api/cases/${caseId}/handoff`);
        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `mecorresponde-expediente-${caseId}.json`;
        link.style.display = 'none';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 0);
        status.innerHTML = '<div class="successBox">Expediente preparado. Puedes conservarlo o facilitarlo en una revisión asistida/profesional.</div>';
      } catch (error) {
        status.innerHTML = `<div class="errorBox">${escapeHtml(error.message)}</div>`;
      } finally {
        button.disabled = false;
        button.textContent = previous;
      }
    });
    return panel;
  }

  function renderCaseHandoff() {
    const panel = ensurePanel();
    if (!panel) return;
    panel.classList.toggle('hidden', !caseId);
  }

  const originalRefresh = refresh;
  refresh = async function (...args) {
    const result = await originalRefresh(...args);
    renderCaseHandoff();
    return result;
  };

  const originalNewCase = newCase;
  newCase = function (...args) {
    const result = originalNewCase(...args);
    renderCaseHandoff();
    return result;
  };

  renderCaseHandoff();
})();
