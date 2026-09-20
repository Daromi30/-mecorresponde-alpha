(() => {

  function ensureOutcomeEvidenceFields() {
    let fields = document.getElementById('outcomeEvidenceFields');
    if (fields) return fields;
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

    if (resolvedOn && resolvedOn > mcrSpainDateIso()) {
      return message('La fecha de cumplimiento no puede estar en el futuro.', 'error');
    }
    if (verified && !channel) {
      return message('Indica cómo se materializó el resultado, o selecciona que no lo sabes.', 'error');
    }
    if (verified && amount <= 0 && detail.length < 3) {
      return message('Describe brevemente qué se cumplió cuando no hubo una devolución de dinero.', 'error');
    }

    const buttons = [...document.querySelectorAll('#outcomeCard .actions button')];
    buttons.forEach(button => { button.disabled = true; });
    try {
      const result = await req(`/api/cases/${caseId}/outcome/evidenced`, {
        method: 'POST',
        body: JSON.stringify({
          result_type: 'FAVORABLE',
          amount_recovered: amount,
          verified_by_user: verified,
          resolved_on: verified && resolvedOn ? resolvedOn : null,
          resolution_channel: verified ? (channel || null) : null,
          non_monetary_result: verified && detail ? detail : null,
        }),
      });
      $('outcome').innerHTML = `<div class="${verified ? 'successBox' : 'notice'}">${
        verified
          ? 'Resultado verificado. El expediente puede cerrarse como resuelto.'
          : 'La empresa ha aceptado, pero el expediente sigue abierto hasta comprobar que cumple.'
      }</div>`;
      await refresh();
      if (verified && result.resolved_on) {
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
    if (date) date.value = '';
    if (channel) channel.value = '';
    if (detail) detail.value = '';
    return result;
  };

  ensureOutcomeEvidenceFields();
})();