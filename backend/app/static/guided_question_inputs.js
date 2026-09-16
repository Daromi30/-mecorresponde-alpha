(() => {
  const originalInputFor = inputFor;
  const originalRenderQuestion = renderQuestion;
  const originalAnswer = answer;

  const supportedExact = new Set([
    'text',
    'boolean',
    'boolean_unknown',
    'money',
    'number',
    'integer',
    'date',
    'date_optional',
    'charges',
    'choice',
  ]);

  const choiceLabels = {
    termination: 'Resolver la compra y recuperar el precio',
    price_reduction: 'Pedir una reducción proporcional del precio',
    undecided: 'Todavía no lo tengo decidido',
  };

  function isSupportedQuestionType(type) {
    const value = String(type || 'text');
    return supportedExact.has(value) || value.startsWith('choice:');
  }

  function choiceOptions(q) {
    if (Array.isArray(q.options) && q.options.length) return q.options;
    const type = String(q.input_type || '');
    if (!type.startsWith('choice:')) return [];
    return type.slice('choice:'.length).split('|').filter(Boolean).map(value => ({
      value,
      label: choiceLabels[value] || value.replaceAll('_', ' '),
    }));
  }

  inputFor = function (q) {
    const type = String(q.input_type || 'text');
    if (type === 'integer') {
      return '<input id="answer" type="number" step="1" inputmode="numeric" placeholder="0">';
    }
    if (type === 'date_optional') {
      return '<input id="answer" type="date">';
    }
    if (type === 'choice' || type.startsWith('choice:')) {
      const options = choiceOptions(q);
      return `<select id="answer"><option value="">Selecciona una opción</option>${options.map(o => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`).join('')}</select>`;
    }
    return originalInputFor(q);
  };

  renderQuestion = function (q) {
    if (q && !q.done && !isSupportedQuestionType(q.input_type)) {
      const area = document.getElementById('questionArea');
      area.innerHTML = '<div class="notice"><b>Esta pregunta necesita revisión.</b><br>No voy a pedirte un dato con un formato que la interfaz no pueda validar. El expediente queda protegido hasta corregir este tipo de entrada.</div>';
      return;
    }
    return originalRenderQuestion(q);
  };

  answer = async function (key, type) {
    if (type !== 'integer') return originalAnswer(key, type);
    clearMessage();
    const el = document.getElementById('answer');
    if (!el || el.value === '') return message('Escribe un número entero para continuar.', 'error');
    const value = Number(el.value);
    if (!Number.isInteger(value)) return message('Este dato debe ser un número entero.', 'error');
    try {
      await req(`/api/cases/${caseId}/facts`, {
        method: 'POST',
        body: JSON.stringify({key, value, state: 'confirmed', user_confirmed: true}),
      });
      await refresh();
    } catch (error) {
      message(escapeHtml(error.message), 'error');
    }
  };

  // The legacy charge editor silently marked every manually entered charge as
  // unverified and used a field name the API does not accept. Keep the legal
  // boundary explicit: a charge only becomes evidence_verified when the user
  // positively confirms they can see that amount/period in a bill, receipt or
  // bank record they hold. No document is claimed to have been uploaded.
  addChargeRow = function () {
    const box = document.getElementById('chargeRows');
    if (!box) return;
    const n = box.children.length + 1;
    box.insertAdjacentHTML('beforeend', `
      <div class="metric chargeRow">
        <b>Cargo ${n}</b>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
          <input class="chargeAmount" type="number" min="0" step="0.01" placeholder="Importe €">
          <input class="chargeDate" type="date" title="Fecha del cargo">
        </div>
        <input class="chargeStart" type="date" title="Inicio del periodo de servicio">
        <input class="chargeEnd" type="date" title="Fin del periodo de servicio">
        <label style="display:flex;gap:8px;align-items:flex-start;margin-top:10px;font-size:13px">
          <input class="chargeEvidence" type="checkbox" style="width:auto;margin-top:3px">
          <span>Confirmo que puedo comprobar este cargo y sus datos en una factura, recibo o movimiento bancario que tengo.</span>
        </label>
      </div>`);
  };

  saveCharges = async function () {
    const rows = [...document.querySelectorAll('.chargeRow')];
    const charges = rows.map(row => ({
      amount: Number(row.querySelector('.chargeAmount').value || 0),
      charged_at: row.querySelector('.chargeDate').value || null,
      service_period_start: row.querySelector('.chargeStart').value || null,
      service_period_end: row.querySelector('.chargeEnd').value || null,
      evidence_verified: Boolean(row.querySelector('.chargeEvidence')?.checked),
    })).filter(item => item.amount > 0);

    if (!charges.length) return message('Añade al menos un cargo con importe.', 'error');
    if (!charges.some(item => item.evidence_verified)) {
      message('Puedes guardar los cargos, pero el Motor no los tratará como acreditados hasta que confirmes que puedes comprobarlos documentalmente.', 'error');
    }
    try {
      await req(`/api/cases/${caseId}/charges`, {
        method: 'POST',
        body: JSON.stringify({charges}),
      });
      await refresh();
    } catch (error) {
      message(escapeHtml(error.message), 'error');
    }
  };

  window.mcrGuidedQuestionInputs = {
    isSupportedQuestionType,
    choiceOptions,
  };
})();
