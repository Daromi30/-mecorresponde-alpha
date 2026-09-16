(() => {
  function ensureCommunicationPanel() {
    let panel = document.getElementById('communicationHistoryCard');
    if (panel) return panel;
    const timeline = document.getElementById('caseTimelineCard');
    const quality = document.getElementById('dossierQualityCard');
    const factsPanel = document.querySelector('#workspace details.panel');
    const anchor = timeline || quality || factsPanel;
    if (!anchor?.parentNode) return null;

    panel = document.createElement('div');
    panel.id = 'communicationHistoryCard';
    panel.className = 'panel hidden';
    panel.innerHTML = `
      <div class="label">Comunicaciones</div>
      <h3>Reclamaciones y respuestas registradas</h3>
      <p class="muted">Aquí aparecen únicamente los envíos que has confirmado y las respuestas que has incorporado al expediente.</p>
      <div id="communicationHistory" class="timeline"></div>`;
    anchor.parentNode.insertBefore(panel, anchor.nextSibling);
    return panel;
  }

  function formatDateOnly(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return '';
    const [year, month, day] = value.split('-').map(Number);
    return new Intl.DateTimeFormat('es-ES', {
      day: '2-digit', month: 'short', year: 'numeric'
    }).format(new Date(year, month - 1, day));
  }

  function meta(item) {
    const parts = [];
    const date = formatDateOnly(item.occurred_on);
    if (date) parts.push(date);
    if (item.channel) parts.push(item.channel);
    if (item.reference_number) parts.push(`ref. ${item.reference_number}`);
    return parts.join(' · ');
  }

  async function renderCommunicationHistory() {
    if (!caseId) return;
    const panel = ensureCommunicationPanel();
    if (!panel) return;
    try {
      const data = await req(`/api/cases/${caseId}/communications`);
      const items = data.communications || [];
      if (!items.length) {
        panel.classList.add('hidden');
        return;
      }
      panel.classList.remove('hidden');
      document.getElementById('communicationHistory').innerHTML = items.map(item => {
        const outbound = item.direction === 'OUTBOUND';
        const title = outbound ? 'Reclamación registrada como enviada' : 'Respuesta de la empresa';
        const body = item.body ? `<div>${escapeHtml(item.body)}</div>` : '';
        return `
          <div class="timelineItem">
            <b>${escapeHtml(title)}</b>
            ${body}
            <div class="tiny muted">${escapeHtml(meta(item))}</div>
          </div>`;
      }).join('');
    } catch (_) {
      panel.classList.add('hidden');
    }
  }

  const previousRefresh = refresh;
  refresh = async function (...args) {
    const result = await previousRefresh(...args);
    await renderCommunicationHistory();
    return result;
  };

  const previousNewCase = newCase;
  newCase = function (...args) {
    const result = previousNewCase(...args);
    const panel = document.getElementById('communicationHistoryCard');
    if (panel) panel.classList.add('hidden');
    return result;
  };
})();
