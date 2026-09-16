(() => {
  function ensureTimelinePanel() {
    let panel = document.getElementById('caseTimelineCard');
    if (panel) return panel;
    const quality = document.getElementById('dossierQualityCard');
    const factsPanel = document.querySelector('#workspace details.panel');
    const anchor = quality || factsPanel;
    if (!anchor?.parentNode) return null;

    panel = document.createElement('div');
    panel.id = 'caseTimelineCard';
    panel.className = 'panel hidden';
    panel.innerHTML = `
      <div class="label">Recorrido del expediente</div>
      <h3>Qué ha pasado hasta ahora</h3>
      <p class="muted">Este historial resume los hitos del proceso. No muestra registros técnicos internos ni cambia el diagnóstico jurídico.</p>
      <div id="caseTimeline" class="timeline"></div>`;
    anchor.parentNode.insertBefore(panel, anchor.nextSibling);
    return panel;
  }

  function formatMoment(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat('es-ES', {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
    }).format(date);
  }

  function formatCalendarDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return '';
    const [year, month, day] = value.split('-').map(Number);
    const localDate = new Date(year, month - 1, day);
    if (Number.isNaN(localDate.getTime())) return '';
    return new Intl.DateTimeFormat('es-ES', {
      day: '2-digit', month: 'short', year: 'numeric'
    }).format(localDate);
  }

  function communicationDateFor(event, communications) {
    if (event.type === 'CLAIM_SUBMITTED') {
      const outbound = communications.find(item => item.direction === 'OUTBOUND' && item.kind === 'CLAIM_SUBMISSION');
      return outbound?.occurred_on || null;
    }
    if (event.type === 'CLAIM_ACCEPTED_PENDING_EXECUTION') {
      const inboundDates = communications
        .filter(item => item.direction === 'INBOUND' && item.kind === 'COMPANY_RESPONSE' && item.occurred_on)
        .map(item => item.occurred_on);
      return inboundDates.length === 1 ? inboundDates[0] : null;
    }
    return null;
  }

  function eventTimeCopy(event, communications) {
    const recorded = formatMoment(event.at);
    const realDate = event.resolved_on || communicationDateFor(event, communications);
    const occurred = formatCalendarDate(realDate);
    if (event.resolved_on && occurred && recorded) return `Cumplido: ${occurred} · Confirmado: ${recorded}`;
    if (event.resolved_on && occurred) return `Cumplido: ${occurred}`;
    if (occurred) return occurred;
    return recorded;
  }

  async function renderCaseTimeline() {
    if (!caseId) return;
    const panel = ensureTimelinePanel();
    if (!panel) return;
    try {
      const data = await req(`/api/cases/${caseId}/timeline`);
      let communications = [];
      try {
        const history = await req(`/api/cases/${caseId}/communications`);
        communications = history.communications || [];
      } catch (_) {
        // Timeline remains usable with technical record times if communication history is unavailable.
      }
      const events = data.events || [];
      if (!events.length) {
        panel.classList.add('hidden');
        return;
      }
      panel.classList.remove('hidden');
      document.getElementById('caseTimeline').innerHTML = events.map(event => `
        <div class="timelineItem">
          <b>${escapeHtml(event.label || '')}</b>
          <div>${escapeHtml(event.detail || '')}</div>
          <div class="tiny muted">${escapeHtml(eventTimeCopy(event, communications))}</div>
        </div>`).join('');
    } catch (_) {
      panel.classList.add('hidden');
    }
  }

  const previousRefresh = refresh;
  refresh = async function (...args) {
    const result = await previousRefresh(...args);
    await renderCaseTimeline();
    return result;
  };

  const previousNewCase = newCase;
  newCase = function (...args) {
    const result = previousNewCase(...args);
    const panel = document.getElementById('caseTimelineCard');
    if (panel) panel.classList.add('hidden');
    return result;
  };
})();
