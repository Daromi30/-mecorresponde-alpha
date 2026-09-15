(() => {
  function ensureDialog() {
    let dialog = document.getElementById('caseDeletionDialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'caseDeletionDialog';
    dialog.innerHTML = `
      <div class="accountModal">
        <div class="accountHead"><div><div class="label">Eliminar expediente</div><h2>Borrar este caso</h2></div><button type="button" class="closeButton">Cerrar</button></div>
        <div class="errorBox"><b>Esta acción es permanente.</b> Se eliminarán los datos de este expediente y, cuando existan, sus documentos almacenados.</div>
        <label for="caseDeleteConfirmation"><b>Escribe ELIMINAR para confirmar</b></label>
        <input id="caseDeleteConfirmation" type="text" autocomplete="off" spellcheck="false">
        <div class="actions"><button type="button" id="confirmCaseDeletion">Eliminar este expediente</button></div>
        <div id="caseDeletionStatus"></div>
      </div>`;
    document.body.appendChild(dialog);
    dialog.querySelector('.closeButton').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    dialog.querySelector('#confirmCaseDeletion').addEventListener('click', async () => {
      const confirmation = dialog.querySelector('#caseDeleteConfirmation').value.trim();
      const status = dialog.querySelector('#caseDeletionStatus');
      if (confirmation !== 'ELIMINAR') {
        status.innerHTML = '<div class="errorBox">Escribe ELIMINAR exactamente para confirmar.</div>';
        return;
      }
      if (!caseId) {
        status.innerHTML = '<div class="errorBox">No hay un expediente abierto.</div>';
        return;
      }
      const button = dialog.querySelector('#confirmCaseDeletion');
      button.disabled = true;
      try {
        await req(`/api/cases/${caseId}`, {
          method: 'DELETE',
          body: JSON.stringify({confirmation: 'DELETE'}),
        });
        dialog.close();
        if (typeof currentUser !== 'undefined' && currentUser && typeof renderAccountState === 'function') {
          renderAccountState();
        }
        newCase();
        message('Expediente eliminado.', 'success');
      } catch (error) {
        status.innerHTML = `<div class="errorBox">${escapeHtml(error.message)}</div>`;
      } finally {
        button.disabled = false;
      }
    });
    return dialog;
  }

  function ensureCaseDeletionControl() {
    const workspace = document.getElementById('workspace');
    if (!workspace || document.getElementById('openCaseDeletion')) return;
    const actions = [...workspace.querySelectorAll(':scope > .actions')].pop();
    if (!actions) return;
    const button = document.createElement('button');
    button.id = 'openCaseDeletion';
    button.type = 'button';
    button.className = 'ghost';
    button.textContent = 'Eliminar este expediente';
    button.style.color = 'var(--bad)';
    button.style.borderColor = '#d9aaa6';
    button.addEventListener('click', () => {
      if (!caseId) return;
      const dialog = ensureDialog();
      dialog.querySelector('#caseDeleteConfirmation').value = '';
      dialog.querySelector('#caseDeletionStatus').innerHTML = '';
      dialog.showModal();
    });
    actions.appendChild(button);
  }

  ensureCaseDeletionControl();
})();
