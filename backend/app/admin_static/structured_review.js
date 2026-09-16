(() => {
  const RESERVED_PREFIXES = ['system.', 'legal.', 'rule.', 'decision.', 'action.'];

  function valueInput(rowId) {
    return `
      <div style="display:grid;grid-template-columns:minmax(160px,1fr) 150px minmax(180px,1fr) 130px;gap:8px;margin:8px 0;align-items:start" data-structured-row="${rowId}">
        <div>
          <div class="meta">Clave del hecho</div>
          <input class="structuredKey" list="knownFactKeys" placeholder="electricity... / purchase..." style="min-width:0;width:100%">
        </div>
        <div>
          <div class="meta">Tipo</div>
          <select class="structuredType" style="width:100%;padding:9px;border:1px solid #d1d5db;border-radius:8px">
            <option value="text">Texto</option>
            <option value="number">Número</option>
            <option value="true">Sí</option>
            <option value="false">No</option>
            <option value="date">Fecha</option>
            <option value="unknown">Desconocido</option>
          </select>
        </div>
        <div>
          <div class="meta">Valor confirmado</div>
          <input class="structuredValue" type="text" style="min-width:0;width:100%">
        </div>
        <div>
          <div class="meta">Importancia</div>
          <select class="structuredMateriality" style="width:100%;padding:9px;border:1px solid #d1d5db;border-radius:8px">
            <option value="critical">Crítico</option>
            <option value="relevant">Relevante</option>
            <option value="context">Contexto</option>
          </select>
        </div>
        <div style="grid-column:1/-1;display:flex;gap:8px;align-items:center">
          <input class="structuredNote" type="text" placeholder="Nota/evidencia del revisor (opcional)" style="min-width:0;flex:1">
          <button type="button" class="secondary removeStructuredFact">Quitar</button>
        </div>
      </div>`;
  }

  function parseValue(row) {
    const type = row.querySelector('.structuredType').value;
    const raw = row.querySelector('.structuredValue').value.trim();
    if (type === 'unknown') return {state: 'unknown', value: null};
    if (type === 'true') return {state: 'confirmed', value: true};
    if (type === 'false') return {state: 'confirmed', value: false};
    if (type === 'number') {
      if (raw === '' || !Number.isFinite(Number(raw))) throw new Error('Hay un valor numérico inválido.');
      return {state: 'confirmed', value: Number(raw)};
    }
    if (type === 'date') {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) throw new Error('Las fechas deben tener formato AAAA-MM-DD.');
      return {state: 'confirmed', value: raw};
    }
    if (!raw) throw new Error('Hay un hecho sin valor.');
    return {state: 'confirmed', value: raw};
  }

  function validateKey(key) {
    const normalized = key.trim();
    if (!normalized.includes('.')) throw new Error('Cada hecho debe usar una clave con namespace, por ejemplo purchase.delivery_date.');
    if (RESERVED_PREFIXES.some(prefix => normalized.toLowerCase().startsWith(prefix))) {
      throw new Error('Ese namespace está reservado y no puede modificarse desde revisión humana.');
    }
    return normalized;
  }

  function verticalLabel(vertical) {
    if (vertical === 'electricity') return 'Electricidad';
    if (vertical === 'purchases') return 'Compras y garantías';
    return vertical || 'Otra vertical';
  }

  async function enhanceAssistedReclassification(c, reviewId, review, completeSection) {
    if (review?.reason !== 'UNSUPPORTED_CLASSIFICATION') return false;
    if (document.getElementById('assistedReclassificationSection')) return true;

    completeSection.style.display = 'none';
    const section = document.createElement('section');
    section.id = 'assistedReclassificationSection';
    section.innerHTML = `
      <h3>Reclasificar al Motor</h3>
      <div class="meta">Este expediente no pudo clasificarse automáticamente. La revisión humana puede corregir solo el enrutamiento hacia una familia ya registrada; no puede introducir un veredicto, una ley, una cantidad, un plazo ni un organismo.</div>
      <div style="margin-top:10px">
        <div class="meta">Familia de resolución</div>
        <select id="assistedTargetFamily" disabled style="width:100%;padding:9px;border:1px solid #d1d5db;border-radius:8px">
          <option value="">Cargando familias registradas…</option>
        </select>
      </div>
      <div style="margin-top:10px">
        <div class="meta">Motivo de la reclasificación</div>
        <textarea id="assistedRoutingDecision" placeholder="Qué elementos del relato permiten encajar el expediente en esta familia, sin resolver todavía el fondo jurídico"></textarea>
      </div>
      <button type="button" id="reclassifyAssistedReview" disabled>Reclasificar y continuar el intake</button>
      <div id="assistedRoutingResult"></div>`;
    completeSection.parentNode.insertBefore(section, completeSection);

    const select = document.getElementById('assistedTargetFamily');
    const button = document.getElementById('reclassifyAssistedReview');
    const resultEl = document.getElementById('assistedRoutingResult');

    try {
      const data = await api('/api/admin/review-routing/families');
      const families = data.families || [];
      select.innerHTML = '<option value="">Selecciona una familia registrada</option>' + families.map(item =>
        `<option value="${esc(item.code)}">${esc(item.code)} · ${esc(verticalLabel(item.vertical))} · ${esc(item.title)}</option>`
      ).join('');
      select.disabled = false;
      button.disabled = false;
    } catch (error) {
      resultEl.innerHTML = `<div class="danger" style="margin-top:10px">No se han podido cargar las familias registradas: ${esc(error.message)}</div>`;
      return true;
    }

    button.addEventListener('click', async () => {
      const targetFamily = select.value;
      const decision = document.getElementById('assistedRoutingDecision').value.trim();
      if (!targetFamily) {
        resultEl.innerHTML = '<div class="danger" style="margin-top:10px">Selecciona una familia del Motor.</div>';
        return;
      }
      if (decision.length < 3) {
        resultEl.innerHTML = '<div class="danger" style="margin-top:10px">Explica brevemente por qué el relato debe entrar en esa familia.</div>';
        return;
      }

      button.disabled = true;
      button.textContent = 'Reclasificando…';
      try {
        const response = await api(`/api/admin/reviews/${reviewId}/reclassify`, {
          method: 'POST',
          body: JSON.stringify({target_family: targetFamily, reviewer_decision: decision}),
        });
        resultEl.innerHTML = `<div class="meta" style="margin-top:10px"><b>Expediente reclasificado a ${esc(response.family)}.</b> El Motor vuelve al intake y pedirá sus hechos necesarios antes de emitir un diagnóstico.</div>`;
        await refreshAll();
        detailEl.innerHTML = '<div class="empty">La clasificación humana se ha incorporado. El expediente vuelve al flujo normal del Motor sin una conclusión jurídica manual.</div>';
      } catch (error) {
        resultEl.innerHTML = `<div class="danger" style="margin-top:10px">${esc(error.message)}</div>`;
        button.disabled = false;
        button.textContent = 'Reclasificar y continuar el intake';
      }
    });
    return true;
  }

  function enhanceProfessionalEscalation(reviewId, review, completeSection) {
    if (review?.reason !== 'POST_DENIAL_ESCALATION_REVIEW') return false;
    if (document.getElementById('professionalEscalationSection')) return true;

    completeSection.style.display = 'none';
    const section = document.createElement('section');
    section.id = 'professionalEscalationSection';
    section.innerHTML = `
      <h3>Escalado tras la respuesta de la empresa</h3>
      <div class="meta">Si la revisión descubre hechos verificables nuevos, incorpóralos en la revisión estructurada y deja que el Motor vuelva a evaluar. Si el siguiente paso exige criterio jurídico no automatizado, deriva el expediente a revisión profesional. Esta acción no selecciona organismo, vía, plazo, remedio ni probabilidad de éxito.</div>
      <div style="margin-top:10px">
        <div class="meta">Motivo del escalado profesional</div>
        <textarea id="professionalEscalationDecision" placeholder="Explica por qué el Motor debe detenerse y qué necesita revisar el profesional"></textarea>
      </div>
      <button type="button" id="escalateProfessionalReview">Escalar a revisión profesional</button>
      <div id="professionalEscalationResult"></div>`;
    completeSection.parentNode.insertBefore(section, completeSection);

    const button = document.getElementById('escalateProfessionalReview');
    const resultEl = document.getElementById('professionalEscalationResult');
    button.addEventListener('click', async () => {
      const decision = document.getElementById('professionalEscalationDecision').value.trim();
      if (decision.length < 3) {
        resultEl.innerHTML = '<div class="danger" style="margin-top:10px">Explica por qué el expediente requiere revisión profesional.</div>';
        return;
      }
      button.disabled = true;
      button.textContent = 'Escalando…';
      try {
        await api(`/api/admin/reviews/${reviewId}/escalate-professional`, {
          method: 'POST',
          body: JSON.stringify({reviewer_decision: decision}),
        });
        await refreshAll();
        detailEl.innerHTML = '<div class="empty">El expediente ha quedado detenido en revisión profesional. No se ha inventado ninguna vía jurídica automática.</div>';
      } catch (error) {
        resultEl.innerHTML = `<div class="danger" style="margin-top:10px">${esc(error.message)}</div>`;
        button.disabled = false;
        button.textContent = 'Escalar a revisión profesional';
      }
    });
    return true;
  }

  function enhanceProfessionalReviewPending(c, review, completeSection) {
    if (review?.reason !== 'PROFESSIONAL_ESCALATION_REQUIRED') return false;
    completeSection.style.display = 'none';
    if (document.getElementById('professionalReviewPendingSection')) return true;
    const section = document.createElement('section');
    section.id = 'professionalReviewPendingSection';
    section.innerHTML = `
      <h3>Revisión profesional pendiente</h3>
      <div class="meta">El Motor automático se ha detenido aquí. Este expediente requiere criterio profesional antes de definir un siguiente escalado jurídico. Puedes seguir incorporando hechos estructurados si el profesional verifica nueva información; la plataforma no cerrará este punto con una nota genérica.</div>
      <button type="button" class="secondary" id="loadProfessionalHandoff">Cargar dossier para handoff</button>
      <div id="professionalHandoffResult"></div>`;
    completeSection.parentNode.insertBefore(section, completeSection);
    document.getElementById('loadProfessionalHandoff').addEventListener('click', async () => {
      const resultEl = document.getElementById('professionalHandoffResult');
      try {
        const dossier = await api(`/api/admin/cases/${c.id}/handoff`);
        resultEl.innerHTML = `<pre>${esc(JSON.stringify(dossier, null, 2))}</pre>`;
      } catch (error) {
        resultEl.innerHTML = `<div class="danger" style="margin-top:10px">${esc(error.message)}</div>`;
      }
    });
    return true;
  }

  function enhanceStructuredReview(c, reviewId) {
    const completeSection = document.getElementById('completeReview')?.closest('section');
    if (!completeSection || document.getElementById('structuredReviewSection')) return;
    const review = (c.human_reviews || []).find(item => item.id === reviewId);

    if (review?.reason === 'UNSUPPORTED_CLASSIFICATION') {
      enhanceAssistedReclassification(c, reviewId, review, completeSection);
      return;
    }

    enhanceProfessionalEscalation(reviewId, review, completeSection);
    enhanceProfessionalReviewPending(c, review, completeSection);

    const knownKeys = [...new Set((c.facts || []).map(item => item.key).filter(Boolean))].sort();
    const datalist = document.createElement('datalist');
    datalist.id = 'knownFactKeys';
    datalist.innerHTML = knownKeys.map(key => `<option value="${esc(key)}"></option>`).join('');
    detailEl.appendChild(datalist);

    const section = document.createElement('section');
    section.id = 'structuredReviewSection';
    section.innerHTML = `
      <h3>Resolver aportando hechos estructurados</h3>
      <div class="meta">Usa esta vía cuando la revisión confirma o corrige hechos del expediente. El Motor volverá a aplicar sus reglas; aquí no se introduce manualmente el veredicto ni la base jurídica.</div>
      <div id="structuredFactRows"></div>
      <button type="button" class="secondary" id="addStructuredFact">Añadir hecho</button>
      <div style="margin-top:10px">
        <div class="meta">Conclusión del revisor</div>
        <textarea id="structuredReviewerDecision" placeholder="Qué se ha comprobado, qué evidencia lo sustenta y por qué se modifica el expediente"></textarea>
      </div>
      <label style="display:flex;align-items:center;gap:8px;margin:10px 0;font-size:13px">
        <input id="reanalyzeStructuredReview" type="checkbox" checked style="min-width:auto;width:auto"> Reanalizar automáticamente con las reglas del Motor
      </label>
      <button type="button" id="resolveStructuredReview">Guardar hechos y reanalizar</button>
      <div id="structuredReviewResult"></div>`;
    completeSection.parentNode.insertBefore(section, completeSection);

    if (completeSection.style.display !== 'none') {
      const oldHeading = completeSection.querySelector('h3');
      if (oldHeading) oldHeading.textContent = 'Cerrar revisión solo con una nota interna';
      const oldMeta = completeSection.querySelector('.meta');
      if (oldMeta) oldMeta.insertAdjacentHTML('afterend', '<div class="meta">Esta opción no añade hechos estructurados. Úsala solo si no hay nada verificable que incorporar al Motor.</div>');
      const oldButton = document.getElementById('completeReview');
      if (oldButton) oldButton.textContent = 'Completar solo con nota';
    }

    const rows = document.getElementById('structuredFactRows');
    let sequence = 0;
    function addRow() {
      sequence += 1;
      rows.insertAdjacentHTML('beforeend', valueInput(sequence));
      const row = rows.lastElementChild;
      const type = row.querySelector('.structuredType');
      const input = row.querySelector('.structuredValue');
      type.addEventListener('change', () => {
        if (type.value === 'unknown' || type.value === 'true' || type.value === 'false') {
          input.value = '';
          input.disabled = true;
        } else {
          input.disabled = false;
          input.type = type.value === 'number' ? 'number' : type.value === 'date' ? 'date' : 'text';
        }
      });
      row.querySelector('.removeStructuredFact').addEventListener('click', () => row.remove());
    }
    addRow();
    document.getElementById('addStructuredFact').addEventListener('click', addRow);

    document.getElementById('resolveStructuredReview').addEventListener('click', async () => {
      const resultEl = document.getElementById('structuredReviewResult');
      const decision = document.getElementById('structuredReviewerDecision').value.trim();
      if (decision.length < 3) {
        resultEl.innerHTML = '<div class="danger">Escribe una conclusión de revisión.</div>';
        return;
      }
      const rowEls = [...rows.querySelectorAll('[data-structured-row]')];
      if (!rowEls.length) {
        resultEl.innerHTML = '<div class="danger">Añade al menos un hecho estructurado.</div>';
        return;
      }

      try {
        const seen = new Set();
        const factUpdates = rowEls.map(row => {
          const key = validateKey(row.querySelector('.structuredKey').value);
          if (seen.has(key)) throw new Error(`La clave ${key} está repetida.`);
          seen.add(key);
          const parsed = parseValue(row);
          return {
            key,
            value: parsed.value,
            state: parsed.state,
            materiality: row.querySelector('.structuredMateriality').value,
            note: row.querySelector('.structuredNote').value.trim() || null,
          };
        });

        const button = document.getElementById('resolveStructuredReview');
        button.disabled = true;
        button.textContent = 'Guardando y reanalizando…';
        const response = await api(`/api/admin/reviews/${reviewId}/resolve-structured`, {
          method: 'POST',
          body: JSON.stringify({
            reviewer_decision: decision,
            fact_updates: factUpdates,
            reanalyze: document.getElementById('reanalyzeStructuredReview').checked,
          }),
        });
        const diagnosis = response.updated_diagnosis;
        resultEl.innerHTML = `<div class="meta" style="margin-top:10px"><b>Revisión estructurada guardada.</b>${diagnosis ? ` Nuevo resultado del Motor: ${esc(diagnosis.viability || 'calculado')}.` : ''}</div>`;
        await refreshAll();
        detailEl.innerHTML = '<div class="empty">La revisión se ha incorporado al expediente y el Motor ha sido reejecutado cuando correspondía.</div>';
      } catch (error) {
        resultEl.innerHTML = `<div class="danger" style="margin-top:10px">${esc(error.message)}</div>`;
        const button = document.getElementById('resolveStructuredReview');
        if (button) {
          button.disabled = false;
          button.textContent = 'Guardar hechos y reanalizar';
        }
      }
    });
  }

  const baseRenderCase = renderCase;
  renderCase = function(c, reviewId) {
    const result = baseRenderCase(c, reviewId);
    enhanceStructuredReview(c, reviewId);
    return result;
  };

  if (!document.querySelector('script[data-mcr-readiness]')) {
    const script = document.createElement('script');
    script.src = 'readiness.js';
    script.dataset.mcrReadiness = 'true';
    document.body.appendChild(script);
  }
})();
