(() => {
  function localTodayIso() {
    const now = new Date();
    const offset = now.getTimezoneOffset() * 60000;
    return new Date(now.getTime() - offset).toISOString().slice(0, 10);
  }

  function ensureSubmissionPanel() {
    let panel = document.getElementById('submissionEvidencePanel');
    if (panel) return panel;
    const claim = document.getElementById('claim');
    if (!claim) return null;

    panel = document.createElement('div');
    panel.id = 'submissionEvidencePanel';
    panel.className = 'counter';
    panel.innerHTML = `
      <div class="label">Registrar el envío real</div>
      <p class="muted">Indica cómo y cuándo la enviaste de verdad. No asumimos que haya sido hoy: estos datos forman parte de la trazabilidad del expediente y pueden afectar al seguimiento de plazos.</p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div><label for="submissionDate">Fecha de envío</label><input id="submissionDate" type="date" required></div>
        <div><label for="submissionChannel">Canal</label><select id="submissionChannel" required>
          <option value="">Selecciona el canal</option>
          <option value="web_form">Formulario web / área de cliente</option>
          <option value="email">Email</option>
          <option value="phone">Teléfono</option>
          <option value="in_person">Presencial</option>
          <option value="postal_mail">Correo postal</option>
          <option value="burofax">Burofax</option>
          <option value="other">Otro</option>
        </select></div>
      </div>
      <div style="margin-top:10px"><label for="submissionReference">Referencia o número de reclamación <span class="muted">(opcional)</span></label><input id="submissionReference" type="text" maxlength="200" autocomplete="off" placeholder="Ej.: RE-2026-12345"></div>
      <div class="actions"><button id="confirmSubmissionBtn" type="button">Confirmar que ya la envié</button><button id="cancelSubmissionBtn" class="secondary" type="button">Cancelar</button></div>`;
    claim.appendChild(panel);

    const dateInput = document.getElementById('submissionDate');
    dateInput.max = localTodayIso();
    document.getElementById('confirmSubmissionBtn').addEventListener('click', submitRecordedSubmission);
    document.getElementById('cancelSubmissionBtn').addEventListener('click', () => panel.classList.add('hidden'));
    return panel;
  }

  function submissionGuidance(submission) {
    let guidance = 'He registrado el envío con la fecha y el canal que has confirmado.';
    if (submission.legal_response_period_business_days) {
      guidance += ` La norma aplicable fija un máximo de <b>${escapeHtml(submission.legal_response_period_business_days)} días hábiles</b> para contestar.`;
    }
    if (submission.deadline) {
      guidance += ` Fecha de vencimiento verificada: <b>${escapeHtml(submission.deadline)}</b>.`;
    } else if (submission.deadline_status === 'LEGAL_PERIOD_ONLY') {
      guidance += ' No calculo una fecha exacta porque el calendario aplicable al caso no está verificado.';
    } else if (submission.deadline_status === 'NOT_CONFIGURED') {
      guidance += ' No aplico un plazo sectorial que no esté verificado para esta familia.';
    }
    if (submission.legal_basis?.official_url) {
      guidance += ` <a href="${escapeHtml(submission.legal_basis.official_url)}" target="_blank" rel="noopener noreferrer">Ver fuente oficial</a>.`;
    }
    return guidance;
  }

  async function submitRecordedSubmission() {
    clearMessage();
    const date = document.getElementById('submissionDate')?.value || '';
    const channel = document.getElementById('submissionChannel')?.value || '';
    const reference = (document.getElementById('submissionReference')?.value || '').trim();
    if (!date) return message('Indica la fecha real en la que enviaste la reclamación.', 'error');
    if (date > localTodayIso()) return message('La fecha de envío no puede estar en el futuro.', 'error');
    if (!channel) return message('Selecciona el canal por el que enviaste la reclamación.', 'error');

    const button = document.getElementById('confirmSubmissionBtn');
    setBusy(button, true, 'Registrando…');
    try {
      const submission = await req(`/api/cases/${caseId}/submission`, {
        method: 'POST',
        body: JSON.stringify({
          submitted_on: date,
          channel,
          reference_number: reference || null,
        }),
      });
      document.getElementById('submissionEvidencePanel')?.classList.add('hidden');
      $('responseCard').classList.remove('hidden');
      message(submissionGuidance(submission), 'success');
      await refresh();
      $('responseCard').scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) {
      message(escapeHtml(error.message), 'error');
    } finally {
      setBusy(button, false);
    }
  }

  registerSubmission = function () {
    clearMessage();
    const panel = ensureSubmissionPanel();
    if (!panel) return message('No he podido abrir el registro del envío.', 'error');
    panel.classList.remove('hidden');
    const dateInput = document.getElementById('submissionDate');
    if (dateInput) {
      dateInput.max = localTodayIso();
      dateInput.focus();
    }
    panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  };
})();