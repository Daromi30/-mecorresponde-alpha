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

  window.mcrGuidedQuestionInputs = {
    isSupportedQuestionType,
    choiceOptions,
  };
})();
