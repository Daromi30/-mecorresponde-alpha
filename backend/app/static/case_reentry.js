(() => {
  function activeCaseFromHash() {
    const match = window.location.hash.match(/^#case=([0-9a-fA-F-]{36})$/);
    return match ? match[1] : null;
  }

  function rememberActiveCase(id) {
    if (!id) return;
    history.replaceState(null, '', `#case=${encodeURIComponent(id)}`);
  }

  function clearActiveCase() {
    if (!window.location.hash.startsWith('#case=')) return;
    history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
  }

  function showWorkspace() {
    document.getElementById('landing')?.classList.add('hidden');
    document.getElementById('workspace')?.classList.remove('hidden');
  }

  function showLanding() {
    document.getElementById('workspace')?.classList.add('hidden');
    document.getElementById('landing')?.classList.remove('hidden');
  }

  const baseCreateCase = createCase;
  createCase = async function (...args) {
    const result = await baseCreateCase(...args);
    if (caseId) rememberActiveCase(caseId);
    return result;
  };

  const baseOpenOwnedCase = openOwnedCase;
  openOwnedCase = async function (id, ...args) {
    const opened = await baseOpenOwnedCase(id, ...args);
    if (opened === true && caseId === id) rememberActiveCase(caseId);
    return opened;
  };

  const baseNewCase = newCase;
  newCase = function (...args) {
    clearActiveCase();
    return baseNewCase(...args);
  };

  const baseSubmitAccount = submitAccount;
  submitAccount = async function (...args) {
    const wasLogin = accountMode === 'login';
    const result = await baseSubmitAccount(...args);
    if (wasLogin && currentUser && !caseId && activeCaseFromHash()) {
      await restoreActiveCase();
    }
    return result;
  };

  async function restoreActiveCase() {
    if (caseId) return;
    const id = activeCaseFromHash();
    if (!id) return;

    caseId = id;
    showWorkspace();
    try {
      await refresh();
      window.scrollTo({top: 0});
    } catch (error) {
      caseId = null;
      showLanding();
      if (error?.status === 404) {
        if (currentUser) {
          clearActiveCase();
          return;
        }
        message('Este enlace puede corresponder a un expediente guardado en una cuenta. Inicia sesión para intentar reabrirlo.', 'notice');
        return;
      }
      message('No he podido reabrir el expediente ahora. Puedes volver a intentarlo recargando la página.', 'error');
    }
  }

  // The case id is only a non-secret locator. Authorization remains in the
  // HttpOnly case-capability cookie or the authenticated account session.
  restoreActiveCase();
})();
