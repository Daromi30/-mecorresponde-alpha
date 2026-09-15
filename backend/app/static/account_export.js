(() => {
  function ensureAccountExportControls() {
    const signedIn = document.getElementById('signedInAccount');
    if (!signedIn || document.getElementById('accountExportControls')) return;

    const section = document.createElement('div');
    section.id = 'accountExportControls';
    section.style.marginTop = '24px';
    section.style.paddingTop = '18px';
    section.style.borderTop = '1px solid var(--line)';
    section.innerHTML = `
      <div class="label">Copia de tus datos</div>
      <p class="accountNote">Descarga una copia JSON de los datos de tu cuenta y de los expedientes que tienes guardados. No incluye contraseñas, tokens ni secretos internos. Los archivos originales adjuntos no se incrustan en esta copia.</p>
      <button type="button" class="secondary" id="downloadAccountExport">Descargar copia de mis datos</button>
      <div id="accountExportStatus"></div>`;
    signedIn.appendChild(section);

    const button = section.querySelector('#downloadAccountExport');
    const status = section.querySelector('#accountExportStatus');
    button.addEventListener('click', async () => {
      const previous = button.textContent;
      button.disabled = true;
      button.textContent = 'Preparando copia…';
      status.innerHTML = '';
      try {
        const data = await req('/api/auth/export');
        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'mecorresponde-export.json';
        link.style.display = 'none';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 0);
        status.innerHTML = '<div class="successBox">Copia preparada. El archivo contiene los datos estructurados guardados en tu cuenta.</div>';
      } catch (error) {
        status.innerHTML = `<div class="errorBox">${escapeHtml(error.message)}</div>`;
      } finally {
        button.disabled = false;
        button.textContent = previous;
      }
    });
  }

  ensureAccountExportControls();
})();
