(() => {
  let storageStatusPromise = null;
  const uploadResults = new Map();

  function storageStatus() {
    if (!storageStatusPromise) {
      storageStatusPromise = fetch('/health/storage', {credentials: 'same-origin', cache: 'no-store'})
        .then(async response => {
          const body = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error('No se ha podido comprobar el almacenamiento documental.');
          return body;
        })
        .catch(error => ({status: 'error', uploads_allowed: false, reason: error.message}));
    }
    return storageStatusPromise;
  }

  function ensureDocumentPanel() {
    let panel = document.getElementById('documentPanel');
    if (panel) return panel;
    const anchor = document.getElementById('dossierQualityCard') || document.querySelector('#workspace details.panel');
    if (!anchor) return null;
    panel = document.createElement('div');
    panel.id = 'documentPanel';
    panel.className = 'panel';
    anchor.parentNode.insertBefore(panel, anchor);
    return panel;
  }

  function resultMarkup(result) {
    if (!result) return '';
    const extracted = result.extracted && Object.keys(result.extracted).length
      ? `<div class="pre">${escapeHtml(JSON.stringify(result.extracted, null, 2))}</div>`
      : '<p class="muted">No se han extraído datos estructurados automáticamente.</p>';
    const flags = (result.quality_flags || []).length
      ? `<p class="tiny muted">Avisos de extracción: ${escapeHtml(result.quality_flags.join(', '))}</p>`
      : '';
    return `
      <div class="successBox"><b>Documento guardado en el expediente.</b></div>
      <div class="label">Extracción auxiliar</div>
      ${extracted}
      ${flags}
      <p class="tiny muted">Los datos extraídos no se convierten en hechos confirmados automáticamente. Deben ser comprobados antes de influir en una conclusión.</p>`;
  }

  async function uploadDocument(file, panel) {
    if (!file || !caseId) return;
    const button = panel.querySelector('#uploadDocumentButton');
    const result = panel.querySelector('#documentUploadResult');
    button.disabled = true;
    const previous = button.textContent;
    button.textContent = 'Subiendo y comprobando…';
    result.innerHTML = '';
    try {
      const form = new FormData();
      form.append('file', file, file.name);
      const response = await fetch(`/api/cases/${caseId}/documents`, {
        method: 'POST',
        credentials: 'same-origin',
        body: form,
        cache: 'no-store',
      });
      const text = await response.text();
      let body = null;
      try { body = text ? JSON.parse(text) : {}; } catch (_) { body = {detail: text}; }
      if (!response.ok) throw new Error(body?.detail || `Error ${response.status}`);
      uploadResults.set(caseId, body);
      result.innerHTML = resultMarkup(body);
      const input = panel.querySelector('#documentFile');
      if (input) input.value = '';
      await renderDocumentPanel();
    } catch (error) {
      result.innerHTML = `<div class="errorBox">${escapeHtml(error.message)}</div>`;
    } finally {
      button.disabled = false;
      button.textContent = previous;
    }
  }

  async function renderDocumentPanel() {
    if (!caseId) return;
    const panel = ensureDocumentPanel();
    if (!panel) return;
    panel.classList.remove('hidden');
    panel.innerHTML = '<div class="label">Documentación</div><p class="muted">Comprobando si el almacenamiento documental está disponible…</p>';

    const status = await storageStatus();
    if (!caseId) return;
    if (!status.uploads_allowed) {
      panel.innerHTML = `
        <div class="label">Documentación</div>
        <h3>Subida de archivos todavía desactivada</h3>
        <div class="notice">MECORRESPONDE no aceptará documentos hasta disponer de almacenamiento persistente. No se ha enviado ni guardado ningún archivo.</div>
        <p class="tiny muted">El resto del expediente puede seguir probándose con datos introducidos manualmente.</p>`;
      return;
    }

    panel.innerHTML = `
      <div class="label">Documentación</div>
      <h3>Añade una factura, contrato, justificante o respuesta</h3>
      <p class="muted">Formatos admitidos: PDF, JPG/JPEG, PNG, WEBP, TXT y CSV. El servidor valida el tipo real del archivo antes de guardarlo.</p>
      <input id="documentFile" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,.txt,.csv,application/pdf,image/jpeg,image/png,image/webp,text/plain,text/csv">
      <div class="actions"><button id="uploadDocumentButton" type="button">Añadir al expediente</button></div>
      <div id="documentUploadResult">${resultMarkup(uploadResults.get(caseId))}</div>`;
    panel.querySelector('#uploadDocumentButton').addEventListener('click', () => {
      const input = panel.querySelector('#documentFile');
      if (!input.files?.length) {
        panel.querySelector('#documentUploadResult').innerHTML = '<div class="errorBox">Selecciona un archivo.</div>';
        return;
      }
      uploadDocument(input.files[0], panel);
    });
  }

  const baseRefresh = refresh;
  refresh = async function (...args) {
    const result = await baseRefresh(...args);
    await renderDocumentPanel();
    return result;
  };

  const baseNewCase = newCase;
  newCase = function (...args) {
    const previousCaseId = caseId;
    const result = baseNewCase(...args);
    if (previousCaseId) uploadResults.delete(previousCaseId);
    const panel = document.getElementById('documentPanel');
    if (panel) panel.classList.add('hidden');
    return result;
  };
})();
