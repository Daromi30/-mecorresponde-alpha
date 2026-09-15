(() => {
  registerSubmission = async function () {
    clearMessage();
    try {
      const submission = await req(`/api/cases/${caseId}/submission`, {
        method: 'POST',
        body: JSON.stringify({
          submitted_on: new Date().toISOString().slice(0, 10),
          channel: 'user_confirmed',
          reference_number: null,
        }),
      });

      $('responseCard').classList.remove('hidden');
      let guidance = 'He registrado que la reclamación fue enviada.';
      if (submission.legal_response_period_business_days) {
        guidance += ` La norma aplicable fija un máximo de <b>${escapeHtml(submission.legal_response_period_business_days)} días hábiles</b> para contestar.`;
      }
      if (submission.deadline) {
        guidance += ` Fecha de vencimiento verificada: <b>${escapeHtml(submission.deadline)}</b>.`;
      } else if (submission.deadline_status === 'LEGAL_PERIOD_ONLY') {
        guidance += ' No calculo una fecha exacta porque el calendario aplicable al caso no está verificado.';
      }
      if (submission.legal_basis?.official_url) {
        guidance += ` <a href="${escapeHtml(submission.legal_basis.official_url)}" target="_blank" rel="noopener noreferrer">Ver fuente oficial</a>.`;
      }
      message(guidance, 'success');
      await refresh();
      $('responseCard').scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) {
      message(escapeHtml(error.message), 'error');
    }
  };
})();
