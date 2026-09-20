(() => {
  function submissionGuidance(submission) {
    let guidance = 'He registrado el envío con la fecha y el canal que has confirmado.';
    if (submission.legal_response_period_business_days) {
      guidance += ` La norma aplicable fija un máximo de <b>${escapeHtml(submission.legal_response_period_business_days)} días hábiles</b> para contestar.`;
    }
    if (submission.deadline) {
      guidance += ` Fecha de vencimiento verificada: <b>${escapeHtml(submission.deadline)}</b>.`;
    } else if (submission.deadline_status === 'LEGAL_PERIOD_ONLY') {
      guidance += ' No calculo una fecha exacta porque el calendario aplicable al caso no está verificado.';
    } else if (submission.deadline_status === 'NOT_CONFIGURED') {
      guidance += ' No aplico un plazo sectorial que no esté verificado para esta familia.';
    }
    if (submission.legal_basis?.official_url) {
      guidance += ` <a href="${escapeHtml(submission.legal_basis.official_url)}" target="_blank" rel="noopener noreferrer">Ver fuente oficial</a>.`;
    }
    return guidance;
  }

  window.mcrSubmissionGuidance = submissionGuidance;
})();
