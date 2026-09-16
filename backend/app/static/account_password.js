(() => {
  function ensurePasswordDialog() {
    let dialog = document.getElementById('changePasswordDialog');
    if (dialog) return dialog;

    dialog = document.createElement('dialog');
    dialog.id = 'changePasswordDialog';
    dialog.setAttribute('aria-labelledby', 'changePasswordTitle');
    dialog.innerHTML = `
      <div class="accountModal">
        <div class="accountHead">
          <div>
            <div class="label">Seguridad de la cuenta</div>
            <h2 id="changePasswordTitle">Cambiar contraseña</h2>
          </div>
          <button type="button" class="closeButton" id="closeChangePassword">Cerrar</button>
        </div>
        <p class="accountNote">Al cambiarla se cerrarán las demás sesiones abiertas y cualquier enlace pendiente para restablecer la contraseña dejará de funcionar.</p>
        <form id="changePasswordForm" class="accountForm">
          <div><label for="currentPassword">Contraseña actual</label><input id="currentPassword" type="password" autocomplete="current-password" required minlength="10" maxlength="128"></div>
          <div><label for="newPassword">Nueva contraseña</label><input id="newPassword" type="password" autocomplete="new-password" required minlength="10" maxlength="128"></div>
          <div><label for="repeatNewPassword">Repite la nueva contraseña</label><input id="repeatNewPassword" type="password" autocomplete="new-password" required minlength="10" maxlength="128"></div>
          <button id="changePasswordSubmit" type="submit">Guardar nueva contraseña</button>
        </form>
        <div id="changePasswordStatus"></div>
      </div>`;
    document.body.appendChild(dialog);

    dialog.querySelector('#closeChangePassword').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
      if (event.target === dialog) dialog.close();
    });

    dialog.querySelector('#changePasswordForm').addEventListener('submit', async event => {
      event.preventDefault();
      const current = dialog.querySelector('#currentPassword');
      const next = dialog.querySelector('#newPassword');
      const repeat = dialog.querySelector('#repeatNewPassword');
      const submit = dialog.querySelector('#changePasswordSubmit');
      const status = dialog.querySelector('#changePasswordStatus');
      status.innerHTML = '';

      if (next.value !== repeat.value) {
        status.innerHTML = '<div class="errorBox">Las nuevas contraseñas no coinciden.</div>';
        return;
      }
      if (current.value === next.value) {
        status.innerHTML = '<div class="errorBox">La nueva contraseña debe ser distinta.</div>';
        return;
      }

      const previous = submit.textContent;
      submit.disabled = true;
      submit.textContent = 'Guardando…';
      try {
        const result = await req('/api/auth/password-change', {
          method: 'POST',
          body: JSON.stringify({current_password: current.value, new_password: next.value}),
        });
        current.value = '';
        next.value = '';
        repeat.value = '';
        status.innerHTML = `<div class="successBox">Contraseña actualizada. Se han cerrado ${escapeHtml(result.sessions_revoked || 0)} sesión(es) anteriores y esta sesión sigue activa.</div>`;
      } catch (error) {
        status.innerHTML = `<div class="errorBox">${escapeHtml(error.message)}</div>`;
      } finally {
        submit.disabled = false;
        submit.textContent = previous;
      }
    });
    return dialog;
  }

  function ensurePasswordControls() {
    const signedIn = document.getElementById('signedInAccount');
    if (!signedIn || document.getElementById('accountPasswordControls')) return;

    const section = document.createElement('div');
    section.id = 'accountPasswordControls';
    section.style.marginTop = '24px';
    section.style.paddingTop = '18px';
    section.style.borderTop = '1px solid var(--line)';
    section.innerHTML = `
      <div class="label">Seguridad</div>
      <p class="accountNote">Cambia tu contraseña sin depender del correo de recuperación.</p>
      <button type="button" class="secondary" id="openChangePassword">Cambiar contraseña</button>`;
    signedIn.appendChild(section);
    section.querySelector('#openChangePassword').addEventListener('click', () => {
      const dialog = ensurePasswordDialog();
      dialog.querySelector('#currentPassword').value = '';
      dialog.querySelector('#newPassword').value = '';
      dialog.querySelector('#repeatNewPassword').value = '';
      dialog.querySelector('#changePasswordStatus').innerHTML = '';
      dialog.showModal();
      setTimeout(() => dialog.querySelector('#currentPassword').focus(), 0);
    });
  }

  ensurePasswordControls();
})();
