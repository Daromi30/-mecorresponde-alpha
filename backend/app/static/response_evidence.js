(() => {

  function ensureResponseEvidenceFields() {
    let fields = document.getElementById('responseEvidenceFields');
    if (fields) return fields;
    const card = document.getElementById('responseCard');
    const textarea = document.getElementById('responseText');
    if (!card || !textarea) return null;
    const actions = textarea.nextElementSibling;

    fields = document.createElement('div');
    fields.id = 'responseEvidenceFields';
    fields.className = 'counter';
    fields.innerHTML = `
      <div class="label">Datos de la respuesta</div>
      <p class="muted">Registra lo que sepas de la comunicación real. La fecha es opcional: si no la conoces, la dejamos sin confirmar en vez de inventarla.</p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div><label for="responseReceivedOn">Fecha de recepción <span class="muted">(si la sabes)</span></label><input id="responseReceivedOn" type="date"></div>
        <div><label for="responseChannel">Canal</label><select id="responseChannel" required>
          <option value="">Selecciona el canal</option>
          <option value="email">Email</option>
          <option value="web_portal">Área de cliente / web</option>
          <option value="postal_mail">Correo postal</option>
          <option value="phone">Teléfono</option>
          <option value="in_person">Presencial</option>
          <option value="other">Otro</option>
          <option value="unknown">No lo sé</option>
        </select></div>
      </div>
      <div style="margin-top:10px"><label for="responseReference">Referencia de la respuesta <span class="muted">(opcional)</span></label><input id="responseReference" type="text" maxlength="100" autocomplete="off" placeholder="Ej.: RES-2026-9876"></div>`;

    const dateInput = fields.querySelector('#responseReceivedOn');
    dateInput.max = mcrSpainDateIso();
    if (actions?.parentNode === card) card.insertBefore(fields, actions);
    else textarea.insertAdjacentElement('afterend', fields);
    return fields;
  }

  function renderResponseAnalysis(result) {
    const type = result.analysis?.type || 'UNKNOWN';
    let html = `<div class="${type === 'ACCEPTANCE' ? 'successBox' : 'notice'}"><b>${
      type === 'ACCEPTANCE' ? 'La empresa parece aceptar' :
      type === 'PARTIAL' ? 'La empresa acepta solo una parte' :
      type === 'DENIAL' ? 'La empresa rechaza o discute la reclamación' :
      'La respuesta necesita revisión'
    }</b></div>`;
    if (result.updated_diagnosis) {
      html += `<p>Con esta nueva información, el diagnóstico pasa a <b>${escapeHtml(viabilityLabel(result.updated_diagnosis.viability))}</b>.</p>`;
    }
    $('responseResult').innerHTML = html;
    if (type === 'ACCEPTANCE') $('outcomeCard').classList.remove('hidden');
  }

  sendResponse = async function () {
    clearMessage();
    const fields = ensureResponseEvidenceFields();
    const text = $('responseText').value.trim();
    if (text.length < 3) return message('Pega la respuesta de la empresa para analizarla.', 'error');

    const receivedOn = fields?.querySelector('#responseReceivedOn')?.value || '';
    const channel = fields?.querySelector('#responseChannel')?.value || '';
    const reference = (fields?.querySelector('#responseReference')?.value || '').trim();
    if (receivedOn && receivedOn > mcrSpainDateIso()) {
      return message('La fecha de recepción no puede estar en el futuro.', 'error');
    }
    if (!channel) {
      return message('Selecciona el canal de la respuesta, o indica que no lo sabes.', 'error');
    }

    const button = document.querySelector('#responseCard .actions button');
    setBusy(button, true, 'Analizando…');
    try {
      const result = await req(`/api/cases/${caseId}/responses/evidenced`, {
        method: 'POST',
        body: JSON.stringify({
          text,
          received_on: receivedOn || null,
          channel,
          reference_number: reference || null,
        }),
      });
      renderResponseAnalysis(result);
      await refresh();
    } catch (error) {
      message(escapeHtml(error.message), 'error');
    } finally {
      setBusy(button, false);
    }
  };

  const previousNewCase = newCase;
  newCase = function (...args) {
    const result = previousNewCase(...args);
    const text = document.getElementById('responseText');
    const date = document.getElementById('responseReceivedOn');
    const channel = document.getElementById('responseChannel');
    const reference = document.getElementById('responseReference');
    if (text) text.value = '';
    if (date) date.value = '';
    if (channel) channel.value = '';
    if (reference) reference.value = '';
    return result;
  };

  ensureResponseEvidenceFields();
})();