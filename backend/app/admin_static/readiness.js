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
    if (item.severity === 'BETA_BLOCKER') return 'Bloquea beta completa';
    if (item.severity === 'PUBLIC_BETA_BLOCKER') return 'Bloquea beta pública';
    if (item.severity === 'PUBLIC_LAUNCH_BLOCKER') return 'Bloquea lanzamiento público';
    return 'Pendiente';
  }

  function readinessLabel(data) {
    if (data.full_closed_beta_ready && data.public_beta_ready && data.public_launch_ready) {
      return 'Listo para beta y lanzamiento público';
    }
    if (data.full_closed_beta_ready && data.public_beta_ready) return 'Beta pública lista; lanzamiento aún no';
    if (data.full_closed_beta_ready) return 'Beta cerrada completa lista';
    return 'Beta completa todavía bloqueada';
  }

  async function renderReadiness() {
    const panel = ensureReadinessPanel();
    if (!panel) return;
    try {
      const data = await api('/api/admin/readiness');
      const checks = data.checks || [];
      panel.innerHTML = `
        <h2>Readiness de beta</h2>
        <div class="meta">Estado calculado por capacidades reales del sistema; no es una valoración manual.</div>
        <div style="margin:12px 0"><b>${esc(readinessLabel(data))}</b></div>
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px">
          ${checks.map(item => `
            <div style="border:1px solid #e5e7eb;border-radius:9px;padding:10px;background:${item.ok ? '#f0fdf4' : '#fff7ed'}">
              <div><b>${esc(item.label)}</b></div>
              <div class="meta">${esc(statusText(item))}</div>
              <div class="meta">${esc(item.detail)}</div>
            </div>`).join('')}
        </div>
        ${data.beta_blockers?.length ? `<div class="meta" style="margin-top:10px"><b>Bloqueantes de beta completa:</b> ${esc(data.beta_blockers.join(', '))}</div>` : ''}`;
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

  if (!document.querySelector('script[data-mcr-admin-handoff]')) {
    const script = document.createElement('script');
    script.src = 'case_handoff.js';
    script.dataset.mcrAdminHandoff = 'true';
    document.body.appendChild(script);
  }
})();
