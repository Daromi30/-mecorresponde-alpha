(() => {
  function ensureDeleteDialog() {
    let dialog = document.getElementById('deleteAccountDialog');
    if (dialog) return dialog;

    dialog = document.createElement('dialog');
    dialog.id = 'deleteAccountDialog';
    dialog.setAttribute('aria-labelledby', 'deleteAccountTitle');
    dialog.innerHTML = `
      <div class="accountModal">
        <div class="accountHead">
          <div>
            <div class="label">Acción irreversible</div>
            <h2 id="deleteAccountTitle">Eliminar cuenta y expedientes</h2>
          </div>
          <button type="button" class="closeButton" id="closeDeleteAccount">Cerrar</button>
        </div>
        <div class="errorBox">
          Se eliminarán tu cuenta y todos los expedientes guardados en ella, incluidos sus datos y documentos asociados. Esta acción no se puede deshacer.
        </div>
        <form id="deleteAccountForm" class="accountForm">
          <div>
            <label for="deleteAccountPassword">Vuelve a escribir tu contraseña</label>
            <input id="deleteAccountPassword" type="password" autocomplete="current-password" required minlength="10" maxlength="128">
          </div>
          <div>
            <label for="deleteAccountConfirmation">Escribe ELIMINAR para confirmar</label>
            <input id="deleteAccountConfirmation" type="text" autocomplete="off" required maxlength="8" spellcheck="false">
          </div>
          <p class="accountNote">La eliminación solo se ejecutará tras volver a comprobar tu contraseña y la confirmación exacta.</p>
          <button id="deleteAccountSubmit" type="submit" disabled>Eliminar definitivamente</button>
        </form>
        <div id="deleteAccountError"></div>
      </div>`;
    document.body.appendChild(dialog);

    const password = dialog.querySelector('#deleteAccountPassword');
    const confirmation = dialog.querySelector('#deleteAccountConfirmation');
    const submit = dialog.querySelector('#deleteAccountSubmit');
    const error = dialog.querySelector('#deleteAccountError');

    function syncConfirmation() {
      submit.disabled = confirmation.value.trim() !== 'ELIMINAR' || password.value.length < 10;
    }

    password.addEventListener('input', syncConfirmation);
    confirmation.addEventListener('input', syncConfirmation);
    dialog.querySelector('#closeDeleteAccount').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
      if (event.target === dialog) dialog.close();
    });

    dialog.querySelector('#deleteAccountForm').addEventListener('submit', async event => {
      event.preventDefault();
      error.innerHTML = '';
      if (confirmation.value.trim() !== 'ELIMINAR') return;

      const previousText = submit.textContent;
      submit.disabled = true;
      submit.textContent = 'Eliminando…';
      try {
        const result = await req('/api/auth/account', {
          method: 'DELETE',
          body: JSON.stringify({password: password.value, confirmation: 'DELETE'}),
        });

        password.value = '';
        confirmation.value = '';
        dialog.close();
        if ($('accountDialog')?.open) closeAccount();
        currentUser = null;
        renderAccountState();
        newCase();
        message(
          `Cuenta eliminada. Se han eliminado ${escapeHtml(result.cases_deleted || 0)} expediente(s) asociado(s).`,
          'success',
        );
      } catch (err) {
        error.innerHTML = `<div class="errorBox">${escapeHtml(err.message)}</div>`;
      } finally {
        submit.textContent = previousText;
        syncConfirmation();
      }
    });

    return dialog;
  }

  function ensureAccountDeletionControls() {
    const signedIn = document.getElementById('signedInAccount');
    if (!signedIn || document.getElementById('accountDeletionControls')) return;

    const section = document.createElement('div');
    section.id = 'accountDeletionControls';
    section.style.marginTop = '24px';
    section.style.paddingTop = '18px';
    section.style.borderTop = '1px solid var(--line)';
    section.innerHTML = `
      <div class="label">Cuenta y datos</div>
      <p class="accountNote">Puedes eliminar tu cuenta y todos los expedientes guardados en ella. Requiere volver a introducir tu contraseña.</p>
      <button type="button" class="secondary" id="openDeleteAccount">Eliminar mi cuenta y expedientes</button>`;
    signedIn.appendChild(section);
    section.querySelector('#openDeleteAccount').addEventListener('click', () => {
      const dialog = ensureDeleteDialog();
      dialog.querySelector('#deleteAccountPassword').value = '';
      dialog.querySelector('#deleteAccountConfirmation').value = '';
      dialog.querySelector('#deleteAccountSubmit').disabled = true;
      dialog.querySelector('#deleteAccountError').innerHTML = '';
      dialog.showModal();
      setTimeout(() => dialog.querySelector('#deleteAccountPassword').focus(), 0);
    });
  }

  ensureAccountDeletionControls();
})();
