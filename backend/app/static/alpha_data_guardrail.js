(() => {
  function ensureLandingNotice() {
    const landing = document.getElementById('landing');
    const composer = landing?.querySelector('.composer');
    if (!landing || !composer || document.getElementById('alphaDataGuardrail')) return;

    const notice = document.createElement('div');
    notice.id = 'alphaDataGuardrail';
    notice.className = 'notice';
    notice.style.maxWidth = '820px';
    notice.style.margin = '0 auto 14px';
    notice.innerHTML = `
      <b>Prueba interna: usa solo datos ficticios.</b>
      <div class="tiny" style="margin-top:4px">No introduzcas nombres completos, DNI/NIE, direcciones, teléfonos, emails reales, CUPS o números de contrato, datos bancarios ni documentos reales. La beta con datos personales seguirá bloqueada hasta cerrar privacidad e infraestructura.</div>`;
    landing.insertBefore(notice, composer);
  }

  function ensureAccountNotice() {
    const dialog = document.getElementById('accountDialog');
    const modal = dialog?.querySelector('.accountModal');
    if (!modal || document.getElementById('alphaAccountDataGuardrail')) return;

    const note = document.createElement('div');
    note.id = 'alphaAccountDataGuardrail';
    note.className = 'notice';
    note.innerHTML = '<b>Cuenta de prueba.</b> Mientras esta advertencia aparezca, usa un email ficticio y no vincules expedientes con datos personales reales.';
    const tabs = modal.querySelector('.tabs');
    if (tabs) tabs.insertAdjacentElement('afterend', note);
    else modal.prepend(note);
  }

  ensureLandingNotice();
  ensureAccountNotice();
})();
