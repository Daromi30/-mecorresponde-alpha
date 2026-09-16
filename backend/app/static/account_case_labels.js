(() => {
  const verticalLabels = {
    electricity: 'Luz y electricidad',
    purchases: 'Compras y garantías',
    telecommunications: 'Telecomunicaciones',
  };

  loadMyCases = async function () {
    if (!currentUser) return;
    try {
      const data = await req('/api/auth/cases');
      const rows = data.cases || [];
      $('myCases').innerHTML = rows.length
        ? rows.map(caseItem => {
            const area = verticalLabels[caseItem.vertical] || 'Otro ámbito';
            return `<button class="caseLink" onclick="openOwnedCase('${escapeHtml(caseItem.id)}')"><b>${escapeHtml(caseItem.title || 'Expediente')}</b><span>${escapeHtml(humanStatus(caseItem.status))} · ${escapeHtml(area)}</span></button>`;
          }).join('')
        : '<p class="muted">Todavía no has guardado expedientes.</p>';
    } catch (error) {
      $('myCases').innerHTML = '<p class="muted">No he podido cargar tus expedientes.</p>';
    }
  };

  // The base page may have restored an existing session before this enhancement
  // loaded. Re-render immediately so no internal family code remains visible.
  if (currentUser) loadMyCases();
})();
