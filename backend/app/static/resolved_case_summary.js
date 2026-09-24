(() => {
  function ensureResolutionSummaryCard() {
    let card = document.getElementById('resolvedCaseSummaryCard');
    if (card) return card;
    const timeline = document.getElementById('caseTimelineCard');
    const quality = document.getElementById('dossierQualityCard');
    const factsPanel = document.querySelector('#workspace details.panel');
    const anchor = timeline || quality || factsPanel;
    if (!anchor?.parentNode) return null;
    card = document.createElement('div');
    card.id = 'resolvedCaseSummaryCard';
    card.className = 'panel hidden';
    card.innerHTML = '<div class="label">Resultado verificado</div><div id="resolvedCaseSummary"></div>';
    anchor.parentNode.insertBefore(card, anchor.nextSibling);
    return card;
  }

  function formatCalendarDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return '';
    const [year, month, day] = value.split('-').map(Number);
    const localDate = new Date(year, month - 1, day);
    if (Number.isNaN(localDate.getTime())) return '';
    return new Intl.DateTimeFormat('es-ES', {
      day: '2-digit', month: 'long', year: 'numeric'
    }).format(localDate);
  }

  function channelLabel(value) {
    return ({
      bank_or_card_refund: 'Reembolso bancario o en tarjeta',
      invoice_credit_or_rebilling: 'Abono o refacturación',
      cancellation: 'Cancelación',
      repair: 'Reparación',
      replacement: 'Sustitución',
      delivery: 'Entrega',
      contract_restoration: 'Restitución o corrección contractual',
      invoice_correction: 'Corrección de factura',
      unknown: 'No indicado',
      other: 'Otro medio',
    })[value] || value || 'No indicado';
  }

  async function renderResolvedCaseSummary() {
    const card = ensureResolutionSummaryCard();
    if (!card) return;
    if (!caseId || caseData?.status !== 'RESOLVED') {
      card.classList.add('hidden');
      return;
    }

    try {
      const dossier = await req(`/api/cases/${caseId}/handoff`);
      const outcome = (dossier.outcomes || []).find(item => item.verified_by_user) || null;
      if (!outcome) {
        card.classList.add('hidden');
        return;
      }

      const recovered = Number(outcome.amount_recovered || 0);
      const resolvedOn = formatCalendarDate(outcome.resolved_on);
      const detail = (outcome.non_monetary_result || '').trim();
      card.classList.remove('hidden');
      document.getElementById('resolvedCaseSummary').innerHTML = `
        <h3 style="margin:6px 0">Lo que consta como cumplido</h3>
        <div class="diagnosisTop">
          <div class="metric">
            <div class="label">Importe recuperado</div>
            <strong>${escapeHtml(money(recovered))}</strong>
          </div>
          <div class="metric">
            <div class="label">Cómo se cumplió</div>
            <strong>${escapeHtml(channelLabel(outcome.resolution_channel))}</strong>
          </div>
        </div>
        ${resolvedOn ? `<p><b>Fecha real de cumplimiento:</b> ${escapeHtml(resolvedOn)}</p>` : '<p class="muted">No consta una fecha exacta de cumplimiento confirmada.</p>'}
        ${detail ? `<div class="successBox"><b>Resultado no monetario</b><br>${escapeHtml(detail)}</div>` : ''}
        <p class="tiny muted">Este resumen muestra el resultado que quedó verificado en el expediente; no vuelve a calcular el diagnóstico ni modifica el caso.</p>`;
    } catch (_) {
      card.classList.add('hidden');
    }
  }

  const previousRefresh = refresh;
  refresh = async function (...args) {
    const result = await previousRefresh(...args);
    await renderResolvedCaseSummary();
    return result;
  };

  const previousNewCase = newCase;
  newCase = function (...args) {
    const result = previousNewCase(...args);
    const card = document.getElementById('resolvedCaseSummaryCard');
    if (card) card.classList.add('hidden');
    return result;
  };
})();
