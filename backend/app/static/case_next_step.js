(() => {
  function ensureNextStepCard() {
    let card = document.getElementById('caseNextStep');
    if (card) return card;
    const progress = document.getElementById('caseProgress');
    const header = document.querySelector('#workspace .caseHeader');
    if (!header) return null;
    card = document.createElement('div');
    card.id = 'caseNextStep';
    card.className = 'panel';
    card.style.padding = '16px';
    card.style.marginTop = '0';
    if (progress) progress.insertAdjacentElement('afterend', card);
    else header.insertAdjacentElement('afterend', card);
    return card;
  }

  function decision() {
    return Array.isArray(caseData?.decisions) && caseData.decisions.length
      ? caseData.decisions[0]
      : null;
  }

  function currentAction() {
    if (!caseData?.current_action_id || !Array.isArray(caseData.actions)) return null;
    return caseData.actions.find(item => item.id === caseData.current_action_id) || null;
  }

  function isPreparableAction(type) {
    if (!type) return false;
    return type.startsWith('PREPARE_') || [
      'GIVE_ADDITIONAL_DELIVERY_PERIOD',
      'SEND_WITHDRAWAL_NOTICE',
    ].includes(type);
  }

  const documentEvidenceActions = new Set([
    'REQUEST_CONTRACT_OR_OFFER_EVIDENCE',
    'REQUEST_DUPLICATE_CHARGE_EVIDENCE',
    'REQUEST_CONSENT_EVIDENCE',
    'REQUEST_CHARGE_EVIDENCE',
  ]);

  function needsDocumentEvidence(type) {
    return documentEvidenceActions.has(type || '');
  }

  function needsGuidedInput(type) {
    if (!type || needsDocumentEvidence(type)) return false;
    return ['ASK_', 'REQUEST_', 'CONFIRM_', 'CORRECT_', 'CHOOSE_'].some(prefix => type.startsWith(prefix));
  }

  async function resumeWaitAction() {
    if (!caseId) return;
    const response = await fetch(`/api/cases/${caseId}/resume-wait`, {
      method: 'POST',
      headers: {'Accept': 'application/json'},
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_) {
      payload = {};
    }
    if (!response.ok) {
      window.alert(payload.detail || 'El hito temporal todavía no permite continuar.');
      return;
    }
    await refresh();
  }

  function diagnosedActionGuidance(currentDecision, current) {
    const type = current?.type || '';

    if (!current) {
      return {
        title: 'Análisis concluido · no hay una acción adicional',
        body: 'Con los hechos actuales, el Motor ha terminado el análisis sin dejar una reclamación, espera o revisión pendiente. Si aparece un hecho nuevo verificable, el expediente puede volver a analizarse.',
        button: 'Ver diagnóstico',
        action: () => document.getElementById('diagnosisCard')?.scrollIntoView({behavior: 'smooth', block: 'start'}),
      };
    }

    if (isPreparableAction(type) && ['HIGH', 'MEDIUM'].includes(currentDecision?.viability)) {
      return {
        title: 'Prepara la acción con este diagnóstico',
        body: 'Revisa primero el razonamiento, el importe y las fuentes. Después puedes abrir la acción que corresponde a esta fase.',
        button: 'Preparar mi siguiente acción',
        action: () => prepareClaim(),
      };
    }

    if (type.startsWith('WAIT_')) {
      return {
        title: 'Todavía no toca enviar una nueva acción',
        body: 'El Motor ha determinado que esta fase consiste en esperar a que se cumpla el hito indicado. Puedes comprobar de nuevo el expediente; si el hito todavía no ha vencido, no se modificará nada.',
        button: 'Comprobar de nuevo',
        action: () => resumeWaitAction(),
      };
    }

    if (needsDocumentEvidence(type)) {
      return {
        title: 'Aporta la evidencia que falta',
        body: 'El siguiente paso depende de un documento o justificante verificable, no de repetir una respuesta. Abre la documentación del expediente para comprobar si la subida está disponible.',
        button: 'Ir a documentación',
        action: () => document.getElementById('documentPanel')?.scrollIntoView({behavior: 'smooth', block: 'center'}),
      };
    }

    if (needsGuidedInput(type)) {
      return {
        title: 'Completa la decisión que falta',
        body: 'El siguiente paso depende de un dato u opción que debe confirmar el usuario. MECORRESPONDE no elegirá ese hecho por ti.',
        button: 'Continuar con la pregunta',
        action: () => document.getElementById('questionArea')?.scrollIntoView({behavior: 'smooth', block: 'center'}),
      };
    }

    if (type === 'RETURN_GOODS_WITH_PROOF') {
      return {
        title: 'Devuelve el producto y conserva la prueba',
        body: 'El desistimiento ya está ejercitado. Cuando hayas devuelto o enviado el producto, actualiza este expediente y conserva el justificante para poder acreditarlo.',
        button: 'Actualizar devolución',
        action: () => document.getElementById('questionArea')?.scrollIntoView({behavior: 'smooth', block: 'center'}),
      };
    }

    if (type.startsWith('EXPLAIN_') || type.startsWith('NO_') || type.startsWith('MONITOR_') || type.startsWith('CHECK_') || type === 'VERIFY_AND_CLOSE_WITHDRAWAL') {
      return {
        title: 'Revisa la conclusión antes de hacer nada más',
        body: 'El Motor no está proponiendo una reclamación nueva en esta fase. Revisa la explicación y actualiza el expediente solo si aparece un hecho nuevo verificable.',
        button: 'Ver diagnóstico',
        action: () => document.getElementById('diagnosisCard')?.scrollIntoView({behavior: 'smooth', block: 'start'}),
      };
    }

    return {
      title: 'Revisa el siguiente paso del diagnóstico',
      body: 'La acción corriente no es una reclamación preparada automáticamente. MECORRESPONDE no la convertirá en un envío distinto del indicado por el Motor.',
      button: 'Ver diagnóstico',
      action: () => document.getElementById('diagnosisCard')?.scrollIntoView({behavior: 'smooth', block: 'start'}),
    };
  }

  function guidanceFor(status) {
    const currentDecision = decision();
    const current = currentAction();
    if (status === 'INTAKE' || status === 'NEEDS_INFORMATION') {
      return {
        title: 'Completa el dato que falta',
        body: 'Responde la siguiente pregunta del expediente. El Motor no cerrará un diagnóstico mientras falten hechos necesarios.',
        button: 'Continuar con la pregunta',
        action: () => document.getElementById('questionArea')?.scrollIntoView({behavior: 'smooth', block: 'center'}),
      };
    }
    if (status === 'DIAGNOSED') {
      return diagnosedActionGuidance(currentDecision, current);
    }
    if (status === 'READY_TO_SUBMIT') {
      return {
        title: 'Revisa y envía la acción preparada',
        body: 'No marques el envío hasta haberlo hecho realmente. Después registra la fecha, el canal y, si existe, la referencia real.',
        button: 'Abrir acción preparada',
        action: () => prepareClaim(),
      };
    }
    if (status === 'WAITING_RESPONSE') {
      return {
        title: 'Añade la respuesta cuando llegue',
        body: 'El expediente está esperando una respuesta real de la empresa. Cuando la recibas, incorpórala para que el Motor la analice.',
        button: 'Registrar una respuesta',
        action: () => {
          const target = document.getElementById('responseCard');
          target?.classList.remove('hidden');
          target?.scrollIntoView({behavior: 'smooth', block: 'start'});
        },
      };
    }
    if (status === 'RESPONSE_RECEIVED') {
      return {
        title: 'Revisa el análisis de la respuesta',
        body: 'La respuesta ya está incorporada. Comprueba qué argumentos cambian el diagnóstico y cuál es la fase siguiente.',
        button: 'Ver reanálisis',
        action: () => document.getElementById('diagnosisCard')?.scrollIntoView({behavior: 'smooth', block: 'start'}),
      };
    }
    if (status === 'HUMAN_REVIEW') {
      return {
        title: 'Este punto está detenido para revisión humana',
        body: 'No se propone un escalado automático porque faltaría una decisión que el Motor no debe inventar. La revisión debe incorporar hechos verificables antes de reanalizar.',
      };
    }
    if (status === 'REANALYZING') {
      return {
        title: 'Reanalizando con la información revisada',
        body: 'Se han incorporado hechos nuevos o corregidos. El siguiente paso volverá a salir de las reglas del Motor, no de una nota libre.',
      };
    }
    if (status === 'RESOLVED_PENDING_EXECUTION') {
      return {
        title: 'Comprueba que la empresa haya cumplido',
        body: 'Una aceptación no cierra el expediente por sí sola. Registra lo que se ejecutó realmente y el importe recuperado, si lo hubo.',
        button: 'Verificar cumplimiento',
        action: () => {
          const target = document.getElementById('outcomeCard');
          target?.classList.remove('hidden');
          target?.scrollIntoView({behavior: 'smooth', block: 'start'});
        },
      };
    }
    if (status === 'RESOLVED') {
      return {
        title: 'Expediente resuelto',
        body: 'El resultado consta como verificado. El historial conserva los hechos, acciones, comunicaciones y resultado del caso.',
      };
    }
    if (status === 'CLOSED_UNSUPPORTED') {
      return {
        title: 'No hay automatización segura para este caso',
        body: 'MECORRESPONDE no forzará una conclusión fuera de las familias que puede resolver de forma trazable.',
      };
    }
    return {
      title: 'Expediente en curso',
      body: 'Sigue el estado del expediente antes de ejecutar una nueva acción.',
    };
  }

  function renderNextStep() {
    if (!caseId || !caseData) return;
    const card = ensureNextStepCard();
    if (!card) return;
    const guidance = guidanceFor(caseData.status || 'INTAKE');
    card.classList.remove('hidden');
    card.innerHTML = `
      <div class="label">Qué hago ahora</div>
      <h3 style="margin:6px 0">${escapeHtml(guidance.title)}</h3>
      <p class="muted" style="margin:0">${escapeHtml(guidance.body)}</p>
      ${guidance.button ? '<div class="actions"><button type="button" id="caseNextStepAction"></button></div>' : ''}`;
    if (guidance.button) {
      const button = document.getElementById('caseNextStepAction');
      button.textContent = guidance.button;
      button.addEventListener('click', guidance.action);
    }
  }

  const baseRefresh = refresh;
  refresh = async function (...args) {
    const result = await baseRefresh(...args);
    renderNextStep();
    return result;
  };

  const baseNewCase = newCase;
  newCase = function (...args) {
    const result = baseNewCase(...args);
    const card = document.getElementById('caseNextStep');
    if (card) card.classList.add('hidden');
    return result;
  };
})();
