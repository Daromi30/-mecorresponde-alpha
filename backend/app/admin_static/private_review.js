(() => {
  const reasonCodes = {
    APPROVE_FOR_RELEASE: ['CONFIRMED_AS_SUPPORTED'],
    REQUEST_INFORMATION: ['INSUFFICIENT_INFORMATION'],
    REJECT_DIAGNOSIS: ['DIAGNOSIS_REJECTED', 'OUT_OF_SCOPE'],
    BLOCK_ACTION: ['ACTION_BLOCKED'],
    ESCALATE: ['LEGAL_UNCERTAINTY', 'ESCALATION_REQUIRED'],
  };
  const checks = [
    ['facts_reviewed', 'He comprobado los hechos y su procedencia'],
    ['sources_rules_reviewed', 'He comprobado las reglas y fuentes'],
    ['uncertainty_reviewed', 'He comprobado incertidumbres y contraargumentos'],
    ['decision_reviewed', 'He revisado la decisión actual'],
    ['action_reviewed', 'He revisado la acción actual'],
  ];
  const originalRenderCase = renderCase;
  renderCase = function(c, reviewId) {
    const result = originalRenderCase(c, reviewId);
    if (c.mode !== 'PRIVATE_REAL_BETA' || !reviewId) return result;
    const section = document.createElement('section');
    section.id = 'privateReviewPanel';
    section.innerHTML = '<h3>Revisión sustantiva privada</h3><div class="meta">Cargando el contexto vigente y la autorización técnica…</div>';
    detailEl.prepend(section);
    api(`/api/admin/reviews/${reviewId}/context`).then(context => {
      if (!section.isConnected) return;
      const currentFacts = (context.facts || []).map(f =>
        `<tr><td>${esc(f.key)}</td><td>${esc(JSON.stringify(f.value))}</td><td>${esc(f.state)}</td><td>${esc(f.created_by)}</td></tr>`
      ).join('');
      section.innerHTML = `
        <h3>Revisión sustantiva · ${esc(context.family)}</h3>
        <div class="meta">Autorización técnica: ${esc(context.technical_reviewer_authorization)} · Cualificación jurídica profesional: no acreditada por esta autorización</div>
        <div class="meta">Case ${esc(context.case_id)} · Review ${esc(context.review_id)} · Facts ${esc(context.facts_version)} · Decision ${esc(context.decision?.id || 'ninguna')} · Action ${esc(context.action?.id || 'ninguna')}</div>
        <h4>Hechos actuales y procedencia</h4><table><tbody>${currentFacts}</tbody></table>
        <h4>Decisión, acción y cálculo</h4><pre>${esc(JSON.stringify({decision:context.decision, action:context.action, calculation:context.calculation}, null, 2))}</pre>
        <h4>Reglas, fuentes e incertidumbres</h4><pre>${esc(JSON.stringify({rule_evaluations:context.rule_evaluations, sources:context.sources, uncertainties:context.uncertainties, remedies:context.remedies, burden_of_proof:context.burden_of_proof}, null, 2))}</pre>
        <h4>Resolución de este caso</h4>
        <select id="privateOutcome"><option value="">Selecciona una resolución</option>${Object.keys(reasonCodes).map(x => `<option value="${x}">${x}</option>`).join('')}</select>
        <select id="privateReason"><option value="">Selecciona un motivo estructurado</option></select>
        <div id="privateRequestField" style="display:none"><label>Dato estructurado solicitado <select id="privateField"><option value="">Selecciona un campo</option>${(context.requestable_fields||[]).map(x => `<option value="${esc(x.key)}">${esc(x.key)}</option>`).join('')}</select></label></div>
        <div id="privateChecklist" style="display:none"><p>Checklist obligatorio para aprobar:</p>${checks.map(([key,label]) => `<label style="display:block"><input type="checkbox" data-review-check="${key}"> ${esc(label)}</label>`).join('')}</div>
        <button type="button" id="privateResolve">Confirmar resolución</button><div id="privateResult"></div>`;
      const outcome = section.querySelector('#privateOutcome');
      const reason = section.querySelector('#privateReason');
      outcome.addEventListener('change', () => {
        reason.innerHTML = '<option value="">Selecciona un motivo estructurado</option>' +
          (reasonCodes[outcome.value] || []).map(x => `<option value="${x}">${x}</option>`).join('');
        section.querySelector('#privateChecklist').style.display = outcome.value === 'APPROVE_FOR_RELEASE' ? 'block' : 'none';
        section.querySelector('#privateRequestField').style.display = outcome.value === 'REQUEST_INFORMATION' ? 'block' : 'none';
      });
      section.querySelector('#privateResolve').addEventListener('click', async () => {
        const message = section.querySelector('#privateResult');
        if (!outcome.value || !reason.value) { message.textContent = 'Selecciona resolución y motivo.'; return; }
        const button = section.querySelector('#privateResolve');
        let body;
        let url;
        if (outcome.value === 'APPROVE_FOR_RELEASE') {
          const checklist = Object.fromEntries(checks.map(([key]) => [key, section.querySelector(`[data-review-check="${key}"]`).checked]));
          if (!Object.values(checklist).every(Boolean)) { message.textContent = 'Completa todos los controles antes de aprobar.'; return; }
          body = {checklist, reason_code: reason.value};
          url = `/api/admin/reviews/${reviewId}/approve-release`;
        } else {
          const field = section.querySelector('#privateField').value;
          if (outcome.value === 'REQUEST_INFORMATION' && !field) { message.textContent = 'Selecciona un campo permitido.'; return; }
          body = {outcome: outcome.value, reason_code: reason.value,
            requested_fields: outcome.value === 'REQUEST_INFORMATION' ? [field] : []};
          url = `/api/admin/reviews/${reviewId}/resolve-private`;
        }
        button.disabled = true;
        try {
          await api(url, {method:'POST', body:JSON.stringify(body)});
          message.textContent = 'Resolución registrada. Se actualizará el expediente.';
          await refreshAll();
        } catch (error) {
          message.textContent = error.message;
          button.disabled = false;
        }
      });
    }).catch(error => {
      if (section.isConnected) section.innerHTML = `<h3>Revisión sustantiva</h3><div class="danger">No se puede resolver: ${esc(error.message)}</div>`;
    });
    return result;
  };
})();
