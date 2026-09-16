(() => {
  function localTodayIso() {
    const now = new Date();
    const offset = now.getTimezoneOffset() * 60000;
    return new Date(now.getTime() - offset).toISOString().slice(0, 10);
  }

  function ensureSubmissionEvidenceFields() {
    let fields = document.getElementById('submissionEvidenceFields');
    if (fields) return fields;

    const card = document.getElementById('claimCard');
    const claim = document.getElementById('claim');
    if (!card || !claim) return null;
    const actions = claim.nextElementSibling;

    fields = document.createElement('div');
    fields.id = 'submissionEvidenceFields';
    fields.className = 'counter';
    fields.innerHTML = `
      <div class="label">Datos reales del envío</div>
      <p class="muted">Antes de marcar la acción como enviada, registra cuándo y por qué canal la enviaste. MECORRESPONDE no rellenará esos datos por ti.</p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div><label for="submissionSentOn">Fecha de envío</label><input id="submissionSentOn" type="date" required></div>
        <div><label for="submissionChannel">Canal</label><select id="submissionChannel" required>
          <option value="">Selecciona el canal</option>
          <option value="web_form">Formulario web / área de cliente</option>
          <option value="email">Email</option>
          <option value="postal_mail">Correo postal</option>
          <option value="phone">Teléfono</option>
          <option value="in_person">Presencial</option>
          <option value="app_chat">Chat / app</option>
          <option value="other">Otro</option>
          <option value="unknown">No lo sé</option>
        </select></div>
      </div>
      <div style="margin-top:10px"><label for="submissionReference">Referencia o justificante <span class="muted">(opcional)</span></label><input id="submissionReference" type="text" maxlength="100" autocomplete="off" placeholder="Ej.: RECL-2026-12345"></div>`;

    const dateInput = fields.querySelector('#submissionSentOn');
    dateInput.max = localTodayIso();
    if (actions?.parentNode === card) card.insertBefore(fields, actions);
    else claim.insertAdjacentElement('afterend', fields);
    return fields;
  }

  registerSubmission = async function () {
    clearMessage();
    const fields = ensureSubmissionEvidenceFields();
    const sentOn = fields?.querySelector('#submissionSentOn')?.value || '';
    const channel = fields?.querySelector('#submissionChannel')?.value || '';
    const reference = (fields?.querySelector('#submissionReference')?.value || '').trim();

    if (!sentOn) return message('Indica la fecha real en la que enviaste la acción.', 'error');
    if (sentOn > localTodayIso()) return message('La fecha de envío no puede estar en el futuro.', 'error');
    if (!channel) return message('Selecciona el canal de envío, o indica que no lo sabes.', 'error');

    const button = document.querySelector('#claimCard .actions button');
    setBusy(button, true, 'Registrando…');
    try {
      const submission = await req(`/api/cases/${caseId}/submission`, {
        method: 'POST',
        body: JSON.stringify({
          submitted_on: sentOn,
          channel,
          reference_number: reference || null,
        }),
      });
      const deadline = submission.deadline
        ? ` Fecha orientativa calculada: <b>${escapeHtml(submission.deadline)}</b>.`
        : '';
      message(`He registrado el envío con los datos que has indicado.${deadline}`, 'success');
      await refresh();
      const responseCard = document.getElementById('responseCard');
      responseCard?.classList.remove('hidden');
      responseCard?.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) {
      message(escapeHtml(error.message), 'error');
    } finally {
      setBusy(button, false);
    }
  };

  const previousRenderClaim = renderClaim;
  renderClaim = function (...args) {
    const result = previousRenderClaim(...args);
    ensureSubmissionEvidenceFields();
    return result;
  };

  const previousNewCase = newCase;
  newCase = function (...args) {
    const result = previousNewCase(...args);
    const date = document.getElementById('submissionSentOn');
    const channel = document.getElementById('submissionChannel');
    const reference = document.getElementById('submissionReference');
    if (date) date.value = '';
    if (channel) channel.value = '';
    if (reference) reference.value = '';
    return result;
  };
})();
