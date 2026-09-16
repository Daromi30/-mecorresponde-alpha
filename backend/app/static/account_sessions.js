(() => {
  function ensureSessionDialog() {
    let dialog = document.getElementById('sessionSecurityDialog');
    if (dialog) return dialog;

    dialog = document.createElement('dialog');
    dialog.id = 'sessionSecurityDialog';
    dialog.setAttribute('aria-labelledby', 'sessionSecurityTitle');
    dialog.innerHTML = `
      <div class="accountModal">
        <div class="accountHead">
          <div>
            <div class="label">Sesiones de la cuenta</div>
            <h2 id="sessionSecurityTitle">Cerrar otras sesiones</h2>
          </div>
          <button type="button" class="closeButton" id="closeSessionSecurity">Cerrar</button>
        </div>
        <div id="sessionSummary" class="accountNote">Comprobando sesiones activas…</div>
        <form id="revokeSessionsForm" class="accountForm">
          <div>
            <label for="revokeSessionsPassword">Confirma tu contraseña</label>
            <input id="revokeSessionsPassword" type="password" autocomplete="current-password" required minlength="10" maxlength="128">
          </div>
          <p class="accountNote">Se mantendrá abierta únicamente esta sesión. No mostramos ubicaciones ni dispositivos porque MECORRESPONDE no necesita almacenar esa telemetría.</p>
          <button id="revokeSessionsSubmit" type="submit">Cerrar las demás sesiones</button>
        </form>
        <div id="sessionSecurityStatus"></div>
      </div>`;
    document.body.appendChild(dialog);

    dialog.querySelector('#closeSessionSecurity').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
      if (event.target === dialog) dialog.close();
    });

    dialog.querySelector('#revokeSessionsForm').addEventListener('submit', async event => {
      event.preventDefault();
      const password = dialog.querySelector('#revokeSessionsPassword');
      const button = dialog.querySelector('#revokeSessionsSubmit');
      const status = dialog.querySelector('#sessionSecurityStatus');
      const previous = button.textContent;
      button.disabled = true;
      button.textContent = 'Cerrando…';
      status.innerHTML = '';
      try {
        const result = await req('/api/auth/sessions/revoke-others', {
          method: 'POST',
          body: JSON.stringify({password: password.value}),
        });
        password.value = '';
        status.innerHTML = `<div class="successBox">Hecho. Se han cerrado ${escapeHtml(result.sessions_revoked || 0)} sesión(es) adicional(es). Esta sesión sigue abierta.</div>`;
        await loadSessionSummary(dialog);
      } catch (error) {
        status.innerHTML = `<div class="errorBox">${escapeHtml(error.message)}</div>`;
      } finally {
        button.disabled = false;
        button.textContent = previous;
      }
    });
    return dialog;
  }

  async function loadSessionSummary(dialog) {
    const summary = dialog.querySelector('#sessionSummary');
    try {
      const result = await req('/api/auth/sessions');
      const count = Number(result.active_count || 0);
      summary.textContent = count === 1
        ? 'Hay 1 sesión activa: esta sesión.'
        : `Hay ${count} sesiones activas en tu cuenta, incluida esta.`;
    } catch (error) {
      summary.textContent = 'No se ha podido comprobar el número de sesiones.';
    }
  }

  function ensureSessionControls() {
    const signedIn = document.getElementById('signedInAccount');
    if (!signedIn || document.getElementById('accountSessionControls')) return;

    const section = document.createElement('div');
    section.id = 'accountSessionControls';
    section.style.marginTop = '24px';
    section.style.paddingTop = '18px';
    section.style.borderTop = '1px solid var(--line)';
    section.innerHTML = `
      <div class="label">Sesiones</div>
      <p class="accountNote">Si has iniciado sesión en otro navegador o dispositivo, puedes cerrar esas sesiones sin cerrar la actual.</p>
      <button type="button" class="secondary" id="openSessionSecurity">Revisar y cerrar otras sesiones</button>`;
    signedIn.appendChild(section);
    section.querySelector('#openSessionSecurity').addEventListener('click', async () => {
      const dialog = ensureSessionDialog();
      dialog.querySelector('#revokeSessionsPassword').value = '';
      dialog.querySelector('#sessionSecurityStatus').innerHTML = '';
      dialog.showModal();
      await loadSessionSummary(dialog);
      setTimeout(() => dialog.querySelector('#revokeSessionsPassword').focus(), 0);
    });
  }

  ensureSessionControls();
})();
