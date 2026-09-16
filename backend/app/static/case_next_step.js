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

  function guidanceFor(status) {
    const currentDecision = decision();
    if (status === 'INTAKE' || status === 'NEEDS_INFORMATION') {
      return {
        title: 'Completa el dato que falta',
        body: 'Responde la siguiente pregunta del expediente. El Motor no cerrará un diagnóstico mientras falten hechos necesarios.',
        button: 'Continuar con la pregunta',
        action: () => document.getElementById('questionArea')?.scrollIntoView({behavior: 'smooth', block: 'center'}),
      };
    }
    if (status === 'DIAGNOSED' && ['HIGH', 'MEDIUM'].includes(currentDecision?.viability)) {
      return {
        title: 'Prepara la acción con este diagnóstico',
        body: 'Revisa primero el razonamiento, el importe y las fuentes. Después puedes abrir la acción que corresponde a esta fase.',
        button: 'Preparar mi siguiente acción',
        action: () => prepareClaim(),
      };
    }
    if (status === 'DIAGNOSED') {
      return {
        title: 'Revisa el diagnóstico antes de avanzar',
        body: 'Con los hechos actuales el Motor no está proponiendo una reclamación automática. Revisa la explicación y los puntos que podrían cambiarla.',
        button: 'Ver diagnóstico',
        action: () => document.getElementById('diagnosisCard')?.scrollIntoView({behavior: 'smooth', block: 'start'}),
      };
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
