(() => {
  function enforceDeterministicReanalysis() {
    const checkbox = document.getElementById('reanalyzeStructuredReview');
    if (!checkbox) return;
    checkbox.checked = true;
    checkbox.disabled = true;
    const label = checkbox.closest('label');
    if (label) {
      label.innerHTML = '<input id="reanalyzeStructuredReview" type="checkbox" checked disabled style="min-width:auto;width:auto"> Reanalizar automáticamente con las reglas del Motor (obligatorio)';
    }
  }

  const observer = new MutationObserver(enforceDeterministicReanalysis);
  observer.observe(document.getElementById('detail'), {childList: true, subtree: true});
  enforceDeterministicReanalysis();
})();
