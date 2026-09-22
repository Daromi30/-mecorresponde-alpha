(() => {

  function ensureOutcomeEvidenceFields() {
    let fields = document.getElementById('outcomeEvidenceFields');
    if (fields) {
      const dateInput = fields.querySelector('#outcomeResolvedOn');
      if (dateInput) dateInput.max = mcrSpainDateIso();
      return fields;
    }
    const card = document.getElementById('outcomeCard');
    const amount = document.getElementById('recoveredAmount');
    if (!card || !amount) return null;
    const actions = amount.nextElementSibling;

    fields = document.createElement('div');
    fields.id = 'outcomeEvidenceFields';
    fields.className = 'counter';
    fields.innerHTML = `
      <div class="label">Comprobar qué se ha cumplido</div>
      <p class="muted">Registra el resultado real. La fecha es opcional: si no la sabes, la dejamos sin confirmar en lugar de convertir hoy en la fecha de resolución.</p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div><label for="outcomeResolvedOn">Fecha de cumplimiento <span class="muted">(si la sabes)</span></label><input id="outcomeResolvedOn" type="date"></div>
        <div><label for="outcomeChannel">Cómo se materializó</label><select id="outcomeChannel">
          <option value="">Selecciona una opción</option>
          <option value="bank_or_card_refund">Devolución bancaria / tarjeta</option>
          <option value="invoice_credit_or_rebilling">Abono o refacturación</option>
          <option value="repair">Reparación</option>
          <option value="replacement">Sustitución</option>
          <option value="cancellation">Cancelación</option>
          <option value="delivery">Entrega</option>
          <option value="contract_restoration">Restitución/corrección contractual</option>
          <option value="other">Otro</option>
          <option value="unknown">No lo sé</option>
        </select></div>
      </div>
      <div style="margin-top:10px"><label for="outcomeDetail">Qué ocurrió <span class="muted">(especialmente si no hubo devolución de dinero)</span></label><textarea id="outcomeDetail" rows="3" maxlength="2000" placeholder="Ej.: cancelaron el servicio y dejaron de cobrarlo; repararon el producto; corrigieron el contrato…"></textarea></div>`;
    fields.innerHTML += `
      <div style="margin-top:10px"><label for="outcomeRemaining">¿Queda alguna parte material de la respuesta favorable por cumplir?</label>
        <select id="outcomeRemaining">
          <option value="unknown">No lo sé todavía</option>
          <option value="pending">Sí, queda pendiente</option>
          <option value="none">No, he comprobado todas las partes</option>
        </select>
      </div>`;

    const dateInput = fields.querySelector('#outcomeResolvedOn');
    dateInput.max = mcrSpainDateIso();
    if (actions?.parentNode === card) card.insertBefore(fields, actions);
    else amount.insertAdjacentElement('afterend', fields);
    return fields;
  }

  closeCase = async function (verified) {
    clearMessage();
    const fields = ensureOutcomeEvidenceFields();
    const amount = Number($('recoveredAmount').value || 0);
    const resolvedOn = fields?.querySelector('#outcomeResolvedOn')?.value || '';
    const channel = fields?.querySelector('#outcomeChannel')?.value || '';
    const detail = (fields?.querySelector('#outcomeDetail')?.value || '').trim();
    const remaining = fields?.querySelector('#outcomeRemaining')?.value || 'unknown';
    const complete = verified && remaining === 'none';

    if (resolvedOn && resolvedOn > mcrSpainDateIso()) {
      return message('La fecha de cumplimiento no puede estar en el futuro.', 'error');
    }
    if (complete && !channel) {
      return message('Indica cómo se materializó el resultado, o selecciona que no lo sabes.', 'error');
    }
    if (complete && amount <= 0 && detail.length < 3) {
      return message('Describe brevemente qué se cumplió cuando no hubo una devolución de dinero.', 'error');
    }
    if (remaining === 'pending' && detail.length < 3) {
      return message('Explica qué se ha cumplido y qué sigue pendiente.', 'error');
    }

    const buttons = [...document.querySelectorAll('#outcomeCard .actions button')];
    buttons.forEach(button => { button.disabled = true; });
    try {
      const result = await req(`/api/cases/${caseId}/outcome/evidenced`, {
        method: 'POST',
        body: JSON.stringify({
          result_type: 'FAVORABLE',
          amount_recovered: amount,
          verified_by_user: complete,
          remaining_material_commitments: remaining,
          resolved_on: complete && resolvedOn ? resolvedOn : null,
          resolution_channel: channel || null,
          non_monetary_result: detail || null,
        }),
      });
      $('outcome').innerHTML = `<div class="${complete ? 'successBox' : 'notice'}">${
        complete
          ? 'Resultado verificado. El expediente puede cerrarse como resuelto.'
          : 'Queda cumplimiento pendiente o desconocido. El expediente sigue abierto: vuelve a esta verificación cuando puedas comprobarlo.'
      }</div>`;
      await refresh();
      if (complete && result.resolved_on) {
        message(`Resolución registrada para el ${escapeHtml(result.resolved_on)} con los datos que has confirmado.`, 'success');
      }
    } catch (error) {
      message(escapeHtml(error.message), 'error');
    } finally {
      buttons.forEach(button => { button.disabled = false; });
    }
  };

  const previousNewCase = newCase;
  newCase = function (...args) {
    const result = previousNewCase(...args);
    const date = document.getElementById('outcomeResolvedOn');
    const channel = document.getElementById('outcomeChannel');
    const detail = document.getElementById('outcomeDetail');
    const remaining = document.getElementById('outcomeRemaining');
    if (date) date.value = '';
    if (channel) channel.value = '';
    if (detail) detail.value = '';
    if (remaining) remaining.value = 'unknown';
    return result;
  };

  ensureOutcomeEvidenceFields();

  const previousRefresh = refresh;
  refresh = async function (...args) {
    const result = await previousRefresh(...args);
    const fields = ensureOutcomeEvidenceFields();
    const evidence = caseData?.execution_verification;
    if (caseData?.status === 'RESOLVED_PENDING_EXECUTION' && evidence && !evidence.verified) {
      const remaining = fields?.querySelector('#outcomeRemaining');
      const detail = fields?.querySelector('#outcomeDetail');
      const amount = document.getElementById('recoveredAmount');
      const channel = fields?.querySelector('#outcomeChannel');
      if (remaining) remaining.value = evidence.remaining_material_commitments || 'unknown';
      if (detail) detail.value = evidence.non_monetary_result || '';
      if (amount) amount.value = evidence.amount_recovered ?? 0;
      if (channel) channel.value = evidence.resolution_channel || '';
      const explanation = evidence.remaining_material_commitments === 'pending'
        ? 'Hay una parte material pendiente de cumplir.'
        : 'Hay una parte material cuyo cumplimiento aún no se conoce.';
      const recorded = evidence.non_monetary_result
        ? `<p>Lo registrado: ${escapeHtml(evidence.non_monetary_result)}</p>` : '';
      document.getElementById('outcome').innerHTML = `<div class="notice">${explanation}${recorded} Continúa esta verificación cuando dispongas de la confirmación.</div>`;
    }
    return result;
  };
})();
