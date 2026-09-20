(() => {
  function spainDateIso(date = new Date()) {
    const parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Madrid',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(date);
    const values = {};
    for (const part of parts) {
      if (part.type === 'year' || part.type === 'month' || part.type === 'day') {
        values[part.type] = part.value;
      }
    }
    if (!values.year || !values.month || !values.day) {
      throw new Error('Could not resolve Spain civil calendar date');
    }
    return `${values.year}-${values.month}-${values.day}`;
  }

  window.mcrSpainDateIso = spainDateIso;
})();
