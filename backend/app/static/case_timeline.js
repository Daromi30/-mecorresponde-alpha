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

  function eventTimeCopy(event) {
    const recorded = formatMoment(event.at);
    const occurred = formatCalendarDate(event.resolved_on);
    if (occurred && recorded) return `Cumplido: ${occurred} · Confirmado: ${recorded}`;
    if (occurred) return `Cumplido: ${occurred}`;
    return recorded;
  }

  async function renderCaseTimeline() {
    if (!caseId) return;
    const panel = ensureTimelinePanel();
    if (!panel) return;
    try {
      const data = await req(`/api/cases/${caseId}/timeline`);
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
          <div class="tiny muted">${escapeHtml(eventTimeCopy(event))}</div>
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
