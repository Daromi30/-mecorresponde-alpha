(() => {
  const labels = {
    INTAKE: 'Recopilando hechos',
    NEEDS_INFORMATION: 'Falta información',
    DIAGNOSIS_AVAILABLE: 'Diagnóstico disponible',
    ACTION_READY: 'Expediente listo para actuar',
    HUMAN_REVIEW_REQUIRED: 'Necesita revisión humana',
    OUT_OF_AUTOMATED_SCOPE: 'Fuera del alcance automatizado',
  };

  function ensurePanel() {
    let panel = document.getElementById('dossierQualityCard');
    if (panel) return panel;
    const factsPanel = document.querySelector('#workspace details.panel');
    if (!factsPanel) return null;
    panel = document.createElement('div');
    panel.id = 'dossierQualityCard';
    panel.className = 'panel';
    panel.innerHTML = '<div class="label">Calidad del expediente</div><div id="dossierQuality">Cargando…</div>';
    factsPanel.parentNode.insertBefore(panel, factsPanel);
    return panel;
  }

  function metric(label, value) {
    return `<div class="metric"><div class="label">${escapeHtml(label)}</div><strong>${escapeHtml(value)}</strong></div>`;
  }

  async function renderDossierQuality() {
    if (!caseId) return;
    const panel = ensurePanel();
    if (!panel) return;
    try {
      const q = await req(`/api/cases/${caseId}/quality`);
      const facts = q.facts || {};
      const evidence = q.evidence || {};
      const gates = q.gates || {};
      const criticalText = `${facts.critical_confirmed || 0} de ${facts.critical_total || 0}`;
      panel.classList.remove('hidden');
      document.getElementById('dossierQuality').innerHTML = `
        <h3>${escapeHtml(labels[q.readiness] || q.readiness || 'En preparación')}</h3>
        <p class="muted">Aquí se muestra qué parte del expediente está confirmada y trazada. No es una probabilidad de éxito jurídico.</p>
        <div class="diagnosisTop">
          <div>
            ${metric('Hechos críticos confirmados', criticalText)}
            ${metric('Hechos pendientes o desconocidos', (facts.asserted || 0) + (facts.unknown || 0))}
          </div>
          <div>
            ${metric('Hechos con apoyo documental', evidence.document_supported_facts || 0)}
            ${metric('Revisiones humanas abiertas', gates.open_human_reviews || 0)}
          </div>
        </div>
        <div class="tiny muted">Reglas evaluadas en la decisión actual: ${escapeHtml(gates.rules_evaluated || 0)}.</div>`;
    } catch (error) {
      panel.classList.add('hidden');
    }
  }

  const originalRefresh = refresh;
  refresh = async function (...args) {
    const result = await originalRefresh(...args);
    await renderDossierQuality();
    return result;
  };

  const originalNewCase = newCase;
  newCase = function (...args) {
    const result = originalNewCase(...args);
    const panel = document.getElementById('dossierQualityCard');
    if (panel) panel.classList.add('hidden');
    return result;
  };

  function loadEnhancement(src, datasetKey) {
    const selector = `script[data-${datasetKey}]`;
    if (document.querySelector(selector)) return;
    const script = document.createElement('script');
    script.src = src;
    script.setAttribute(`data-${datasetKey}`, 'true');
    document.body.appendChild(script);
  }

  loadEnhancement('/demo/account_deletion.js', 'mcr-account-deletion');
  loadEnhancement('/demo/deadline_guidance.js', 'mcr-deadline-guidance');
  loadEnhancement('/demo/documentation.js', 'mcr-documentation');
})();
