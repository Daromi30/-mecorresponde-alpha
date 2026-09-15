(() => {
  let capabilities = null;
  let resetToken = null;

  async function loadCapabilities() {
    if (capabilities) return capabilities;
    try {
      capabilities = await req('/api/auth/capabilities');
    } catch (_) {
      capabilities = {
        transactional_email_operational: false,
        password_recovery_available: false,
        email_verification_available: false,
        email_verification_enforced: false,
      };
    }
    return capabilities;
  }

  function ensureRecoveryDialog() {
    let dialog = document.getElementById('passwordRecoveryDialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'passwordRecoveryDialog';
    dialog.innerHTML = `
      <div class="accountModal">
        <div class="accountHead"><div><div class="label">Recuperar cuenta</div><h2>Restablecer contraseña</h2></div><button type="button" class="closeButton">Cerrar</button></div>
        <p class="accountNote">Si existe una cuenta para ese email, enviaremos un enlace temporal. La respuesta no confirma si la cuenta existe.</p>
        <form id="passwordRecoveryForm" class="accountForm">
          <div><label for="passwordRecoveryEmail">Email</label><input id="passwordRecoveryEmail" type="email" autocomplete="email" required maxlength="320"></div>
          <button type="submit">Enviar enlace de recuperación</button>
        </form>
        <div id="passwordRecoveryStatus"></div>
      </div>`;
    document.body.appendChild(dialog);
    dialog.querySelector('.closeButton').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    dialog.querySelector('#passwordRecoveryForm').addEventListener('submit', async event => {
      event.preventDefault();
      const email = dialog.querySelector('#passwordRecoveryEmail').value.trim();
      const status = dialog.querySelector('#passwordRecoveryStatus');
      status.innerHTML = '';
      try {
        const result = await req('/api/auth/password-reset/request', {
          method: 'POST',
          body: JSON.stringify({email}),
        });
        status.innerHTML = `<div class="successBox">${escapeHtml(result.message || 'Si existe la cuenta, recibirás instrucciones.')}</div>`;
      } catch (error) {
        status.innerHTML = `<div class="errorBox">${escapeHtml(error.message)}</div>`;
      }
    });
    return dialog;
  }

  function ensureResetConfirmDialog() {
    let dialog = document.getElementById('passwordResetConfirmDialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'passwordResetConfirmDialog';
    dialog.innerHTML = `
      <div class="accountModal">
        <div class="accountHead"><div><div class="label">Enlace de recuperación</div><h2>Elige una contraseña nueva</h2></div><button type="button" class="closeButton">Cerrar</button></div>
        <form id="passwordResetConfirmForm" class="accountForm">
          <div><label for="passwordResetNew">Nueva contraseña</label><input id="passwordResetNew" type="password" autocomplete="new-password" required minlength="10" maxlength="128"></div>
          <div><label for="passwordResetRepeat">Repite la contraseña</label><input id="passwordResetRepeat" type="password" autocomplete="new-password" required minlength="10" maxlength="128"></div>
          <p class="accountNote">Al cambiarla se cerrarán todas las sesiones abiertas de la cuenta.</p>
          <button type="submit">Cambiar contraseña</button>
        </form>
        <div id="passwordResetConfirmStatus"></div>
      </div>`;
    document.body.appendChild(dialog);
    dialog.querySelector('.closeButton').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    dialog.querySelector('#passwordResetConfirmForm').addEventListener('submit', async event => {
      event.preventDefault();
      const password = dialog.querySelector('#passwordResetNew').value;
      const repeated = dialog.querySelector('#passwordResetRepeat').value;
      const status = dialog.querySelector('#passwordResetConfirmStatus');
      if (password !== repeated) {
        status.innerHTML = '<div class="errorBox">Las contraseñas no coinciden.</div>';
        return;
      }
      if (!resetToken) {
        status.innerHTML = '<div class="errorBox">El enlace de recuperación no es válido.</div>';
        return;
      }
      try {
        await req('/api/auth/password-reset/confirm', {
          method: 'POST',
          body: JSON.stringify({token: resetToken, password}),
        });
        resetToken = null;
        status.innerHTML = '<div class="successBox">Contraseña actualizada. Ya puedes entrar con la nueva contraseña.</div>';
        if (typeof currentUser !== 'undefined') currentUser = null;
        if (typeof renderAccountState === 'function') renderAccountState();
      } catch (error) {
        status.innerHTML = `<div class="errorBox">${escapeHtml(error.message)}</div>`;
      }
    });
    return dialog;
  }

  async function ensureAccountRecoveryControls() {
    const caps = await loadCapabilities();
    const modal = document.querySelector('#accountDialog .accountModal');
    if (modal && caps.password_recovery_available && !document.getElementById('openPasswordRecovery')) {
      const button = document.createElement('button');
      button.id = 'openPasswordRecovery';
      button.type = 'button';
      button.className = 'secondary';
      button.style.marginTop = '12px';
      button.textContent = 'He olvidado mi contraseña';
      button.addEventListener('click', () => {
        const dialog = ensureRecoveryDialog();
        dialog.querySelector('#passwordRecoveryStatus').innerHTML = '';
        dialog.showModal();
      });
      modal.appendChild(button);
    }

    const signedIn = document.getElementById('signedInAccount');
    const user = typeof currentUser !== 'undefined' ? currentUser : null;
    if (
      signedIn && user && !user.email_verified && caps.email_verification_available
      && !document.getElementById('emailVerificationControls')
    ) {
      const section = document.createElement('div');
      section.id = 'emailVerificationControls';
      section.style.marginTop = '18px';
      section.innerHTML = `
        <div class="notice"><b>Email pendiente de verificar.</b><div class="tiny" style="margin-top:4px">La verificación demuestra que controlas la dirección asociada a la cuenta.</div></div>
        <button type="button" class="secondary" id="sendVerificationEmail">Enviar email de verificación</button>
        <div id="emailVerificationStatus"></div>`;
      signedIn.appendChild(section);
      section.querySelector('#sendVerificationEmail').addEventListener('click', async () => {
        const status = section.querySelector('#emailVerificationStatus');
        try {
          await req('/api/auth/email-verification/request', {method: 'POST', body: '{}'});
          status.innerHTML = '<div class="successBox">Email enviado. El enlace caduca en 24 horas.</div>';
        } catch (error) {
          status.innerHTML = `<div class="errorBox">${escapeHtml(error.message)}</div>`;
        }
      });
    }
  }

  async function processActionFragment() {
    const raw = location.hash.startsWith('#') ? location.hash.slice(1) : '';
    if (!raw) return;
    const params = new URLSearchParams(raw);
    const verifyToken = params.get('verify-email');
    const passwordToken = params.get('reset-password');
    if (!verifyToken && !passwordToken) return;

    // Remove the one-time secret from browser history/address bar immediately after
    // capturing it. Confirmation is sent in a POST body, not in a request URL.
    history.replaceState(null, '', location.pathname + location.search);

    if (verifyToken) {
      try {
        const result = await req('/api/auth/email-verification/confirm', {
          method: 'POST',
          body: JSON.stringify({token: verifyToken}),
        });
        if (typeof currentUser !== 'undefined') currentUser = result.user;
        if (typeof renderAccountState === 'function') renderAccountState();
        message('Email verificado correctamente.', 'success');
      } catch (error) {
        message(error.message, 'error');
      }
      return;
    }

    resetToken = passwordToken;
    const dialog = ensureResetConfirmDialog();
    dialog.querySelector('#passwordResetConfirmStatus').innerHTML = '';
    dialog.showModal();
  }

  loadCapabilities().then(ensureAccountRecoveryControls);
  processActionFragment();

  const observer = new MutationObserver(() => {
    ensureAccountRecoveryControls();
  });
  observer.observe(document.body, {childList: true, subtree: true});
})();
