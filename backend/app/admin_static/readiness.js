(() => {
  function ensureReadinessPanel() {
    let panel = document.getElementById('betaReadinessPanel');
    if (panel) return panel;
    const metrics = document.getElementById('metrics');
    if (!metrics) return null;
    panel = document.createElement('div');
    panel.id = 'betaReadinessPanel';
    panel.className = 'panel';
    panel.style.marginBottom = '16px';
    metrics.parentNode.insertBefore(panel, metrics);
    return panel;
  }

  function statusText(item) {
    if (item.ok) return 'Operativo';
    if (item.severity === 'INTERNAL_BETA_BLOCKER') return 'Bloquea beta interna';
    if (item.severity === 'BETA_BLOCKER') return 'Bloquea beta con datos reales';
    if (item.severity === 'PUBLIC_BETA_BLOCKER') return 'Bloquea beta pública';
    if (item.severity === 'PUBLIC_LAUNCH_BLOCKER') return 'Bloquea lanzamiento público';
    return 'Pendiente';
  }

  function readinessLabel(data) {
    if (data.full_closed_beta_ready && data.public_beta_ready && data.public_launch_ready) {
      return 'Listo para beta y lanzamiento público';
    }
    if (data.full_closed_beta_ready && data.public_beta_ready) return 'Beta pública lista; lanzamiento aún no';
    if (data.full_closed_beta_ready) return 'Beta cerrada con datos reales lista';
    if (data.synthetic_internal_beta_ready) return 'Beta interna con datos ficticios lista para prueba manual';
    return 'Beta interna todavía bloqueada';
  }

  async function renderReadiness() {
    const panel = ensureReadinessPanel();
    if (!panel) return;
    try {
      const data = await api('/api/admin/readiness');
      const checks = data.checks || [];
      panel.innerHTML = `
        <h2>Readiness de beta</h2>
        <div class="meta">Estado calculado por capacidades reales del sistema; separa pruebas internas con datos ficticios de cualquier uso con datos reales.</div>
        <div style="margin:12px 0"><b>${esc(readinessLabel(data))}</b></div>
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px">
          ${checks.map(item => `
            <div style="border:1px solid #e5e7eb;border-radius:9px;padding:10px;background:${item.ok ? '#f0fdf4' : '#fff7ed'}">
              <div><b>${esc(item.label)}</b></div>
              <div class="meta">${esc(statusText(item))}</div>
              <div class="meta">${esc(item.detail)}</div>
            </div>`).join('')}
        </div>
        ${data.internal_beta_blockers?.length ? `<div class="meta" style="margin-top:10px"><b>Bloqueantes de beta interna:</b> ${esc(data.internal_beta_blockers.join(', '))}</div>` : ''}
        ${data.beta_blockers?.length ? `<div class="meta" style="margin-top:6px"><b>Pendientes antes de datos reales:</b> ${esc(data.beta_blockers.filter(x => !(data.internal_beta_blockers || []).includes(x)).join(', '))}</div>` : ''}`;
    } catch (error) {
      panel.innerHTML = `<h2>Readiness de beta</h2><div class="danger">No se ha podido calcular: ${esc(error.message)}</div>`;
    }
  }

  const baseRefreshAll = refreshAll;
  refreshAll = async function (...args) {
    const result = await baseRefreshAll(...args);
    await renderReadiness();
    return result;
  };

  function loadAdminEnhancement(src, datasetKey) {
    const selector = `script[data-${datasetKey}]`;
    if (document.querySelector(selector)) return;
    const script = document.createElement('script');
    script.src = src;
    script.async = false;
    script.setAttribute(`data-${datasetKey}`, 'true');
    document.body.appendChild(script);
  }

  loadAdminEnhancement('case_handoff.js', 'mcr-admin-handoff');
  loadAdminEnhancement('review_context.js', 'mcr-review-context');
})();
