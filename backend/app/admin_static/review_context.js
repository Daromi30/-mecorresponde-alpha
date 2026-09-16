(() => {
  function formatDateOnly(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return 'Fecha no indicada';
    const [year, month, day] = value.split('-').map(Number);
    return new Intl.DateTimeFormat('es-ES', {
      day: '2-digit', month: 'short', year: 'numeric'
    }).format(new Date(year, month - 1, day));
  }

  function channelLabel(value) {
    const labels = {
      bank_or_card_refund: 'Reembolso bancario o en tarjeta',
      invoice_credit: 'Abono en factura',
      service_restored: 'Servicio restablecido',
      replacement: 'Sustitución',
      repair: 'Reparación',
      unknown: 'No indicado',
    };
    return labels[value] || value || 'No indicado';
  }

  function communicationTable(items) {
    if (!items.length) return '<div class="empty">No hay comunicaciones registradas.</div>';
    return `<table><thead><tr><th>Tipo</th><th>Fecha real</th><th>Canal / referencia</th><th>Contenido</th></tr></thead><tbody>${items.map(item => {
      const kind = item.direction === 'OUTBOUND' ? 'Reclamación enviada' : 'Respuesta recibida';
      const reference = item.reference_number ? ` · ref. ${esc(item.reference_number)}` : '';
      return `<tr>
        <td><b>${esc(kind)}</b></td>
        <td>${esc(formatDateOnly(item.occurred_on))}</td>
        <td>${esc(item.channel || 'No indicado')}${reference}</td>
        <td>${item.body ? esc(item.body) : '<span class="meta">Sin texto almacenado</span>'}</td>
      </tr>`;
    }).join('')}</tbody></table>`;
  }

  function outcomeTable(items) {
    if (!items.length) return '<div class="empty">Todavía no hay un resultado verificado.</div>';
    return `<table><thead><tr><th>Resultado</th><th>Fecha real</th><th>Recuperado</th><th>Cumplimiento</th></tr></thead><tbody>${items.map(item => `
      <tr>
        <td><b>${item.verified_by_user ? 'Verificado' : 'Pendiente de verificar'}</b></td>
        <td>${esc(formatDateOnly(item.resolved_on))}</td>
        <td>${item.amount_recovered == null ? '—' : esc(euro(item.amount_recovered))}</td>
        <td>${esc(channelLabel(item.resolution_channel))}${item.non_monetary_result ? `<div class="meta">${esc(item.non_monetary_result)}</div>` : ''}</td>
      </tr>`).join('')}</tbody></table>`;
  }

  function enforceMandatoryReanalysis() {
    const input = document.getElementById('reanalyzeStructuredReview');
    if (!input) return;
    input.checked = true;
    input.disabled = true;
    input.setAttribute('aria-label', 'Reanálisis obligatorio con las reglas del Motor');
    const label = input.closest('label');
    if (label) {
      label.title = 'Los hechos estructurados siempre vuelven a pasar por las reglas del Motor.';
    }
  }

  async function renderReviewContext(caseData, reviewId) {
    const old = document.getElementById('reviewOperationalContext');
    if (old) old.remove();

    const section = document.createElement('section');
    section.id = 'reviewOperationalContext';
    section.dataset.caseId = caseData.id;
    section.innerHTML = '<h3>Comunicaciones y resultado</h3><div class="meta">Cargando cronología normalizada…</div>';

    const auditSection = [...detailEl.querySelectorAll('section')].find(item => item.querySelector('h3')?.textContent === 'Auditoría reciente');
    if (auditSection?.parentNode) auditSection.parentNode.insertBefore(section, auditSection);
    else detailEl.appendChild(section);

    try {
      const handoff = await api(`/api/admin/cases/${caseData.id}/handoff`);
      if (!section.isConnected || section.dataset.caseId !== caseData.id || currentReview !== reviewId) return;
      const communications = handoff.communications || [];
      const outcomes = handoff.outcomes || [];
      section.innerHTML = `
        <h3>Comunicaciones y resultado</h3>
        <div class="meta">Las fechas reales proceden de la evidencia registrada por el usuario. Los timestamps técnicos no se presentan como fecha del hecho.</div>
        <h3>Comunicaciones</h3>
        ${communicationTable(communications)}
        <h3>Resultado</h3>
        ${outcomeTable(outcomes)}`;
    } catch (error) {
      if (!section.isConnected || currentReview !== reviewId) return;
      section.innerHTML = `<h3>Comunicaciones y resultado</h3><div class="danger">${esc(error.message)}</div>`;
    }
  }

  const baseRenderCaseForContext = renderCase;
  renderCase = function(c, reviewId) {
    const result = baseRenderCaseForContext(c, reviewId);
    enforceMandatoryReanalysis();
    renderReviewContext(c, reviewId);
    return result;
  };
})();
