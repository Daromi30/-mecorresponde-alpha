(() => {
  function downloadJson(filename, data) {
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  async function enhanceHandoff(caseData) {
    const old = document.getElementById('adminCaseHandoff');
    if (old) old.remove();

    const section = document.createElement('section');
    section.id = 'adminCaseHandoff';
    section.innerHTML = '<h3>Paquete de revisión / escalado</h3><div class="meta">Cargando trazabilidad jurídica…</div>';
    detailEl.appendChild(section);

    try {
      const handoff = await api(`/api/admin/cases/${caseData.id}/handoff`);
      const sources = handoff.legal_provenance || [];
      const sourceRows = sources.length
        ? `<table><tbody>${sources.map(item => `
            <tr>
              <td><b>${esc(item.rule_id)}</b><div class="meta">v${esc(item.version)} · art. ${esc(item.article)}</div></td>
              <td>${item.source ? `<a href="${esc(item.source.official_url)}" target="_blank" rel="noopener noreferrer">${esc(item.source.title)}</a><div class="meta">${esc(item.source.authority)}</div>` : '<span class="danger">Fuente no disponible</span>'}</td>
            </tr>`).join('')}</tbody></table>`
        : '<div class="empty">Este expediente todavía no tiene una evaluación jurídica trazada.</div>';

      section.innerHTML = `
        <h3>Paquete de revisión / escalado</h3>
        <div class="meta">Resumen estructurado del expediente para gestión asistida o revisión profesional. No sustituye la revisión profesional cuando el Motor la exige.</div>
        <div style="margin:10px 0">${sourceRows}</div>
        <button type="button" class="secondary" id="downloadAdminHandoff">Descargar paquete estructurado</button>
        <span class="meta" style="margin-left:8px">${esc(handoff.current_facts?.length || 0)} hechos actuales · ${esc(handoff.open_human_review_count || 0)} revisiones abiertas</span>`;

      document.getElementById('downloadAdminHandoff').addEventListener('click', () => {
        downloadJson(`mecorresponde-handoff-${caseData.id}.json`, handoff);
      });
    } catch (error) {
      section.innerHTML = `<h3>Paquete de revisión / escalado</h3><div class="danger">${esc(error.message)}</div>`;
    }
  }

  const baseRenderCaseForHandoff = renderCase;
  renderCase = function(c, reviewId) {
    const result = baseRenderCaseForHandoff(c, reviewId);
    enhanceHandoff(c);
    return result;
  };
})();
