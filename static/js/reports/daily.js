(function () {
  window.ODE = window.ODE || {};
  const reports = (window.ODE.reports = window.ODE.reports || {});

  function renderLegacyRows(rows) {
    const body = byId('dailyBody');
    if (!body) return;
    body.innerHTML = rows.map(row => `<tr><td>${esc(row.date)}</td><td>${esc(row.report_block)}</td><td>${esc(row.task_number)}</td><td>${esc(row.description)}</td><td>${esc(row.quantity)}</td><td>${esc(row.serial_number)}</td><td>${esc(operationalHistoryText(row.responsible))}</td><td>${esc(operationalHistoryText(row.comment))}</td></tr>`).join('') || '<tr><td class="empty" colspan="8">Нет данных за период</td></tr>';
  }

  async function buildLegacy() {
    const query = new URLSearchParams(formData(byId('dailyForm')));
    try { renderLegacyRows((await request('/api/daily-report?' + query)).rows); }
    catch (error) { notify(error.message, true); }
  }

  async function showUploaded() {
    const id = byId('uploadedReport')?.value;
    if (!id) return;
    try { renderLegacyRows((await request(`/api/uploaded-daily-report?id=${id}`)).rows); }
    catch (error) { notify(error.message, true); }
  }

  async function showUploadedList() {
    const id = byId('uploadedReportList')?.value;
    if (!id) return;
    try {
      const rows = (await request(`/api/uploaded-daily-report?id=${id}`)).rows;
      byId('uploadedReportBody').innerHTML = rows.map(row => `<tr><td>${esc(row.date)}</td><td>${esc(row.report_block)}</td><td>${esc(row.task_number)}</td><td>${esc(row.description)}</td><td>${esc(row.quantity)}</td><td>${esc(row.serial_number)}</td><td>${esc(operationalHistoryText(row.responsible))}</td><td>${esc(operationalHistoryText(row.comment))}</td></tr>`).join('') || '<tr><td class="empty" colspan="8">В отчете нет строк</td></tr>';
    } catch (error) { notify(error.message, true); }
  }

  async function buildShift() {
    const form = byId('shiftForm');
    if (!form?.reportValidity()) return;
    const data = formData(form);
    try {
      const response = await request('/api/work-logs?' + new URLSearchParams({date_from: data.date, date_to: data.date}));
      setText('shiftEngineer', `${state.current_user.first_name || ''} ${state.current_user.last_name || ''}`.trim());
      reports.renderWorkTable('shiftBody', response.logs || [], 'За выбранную смену работ не зафиксировано');
    } catch (error) { notify(error.message, true); }
  }

  const dailyForm = byId('dailyForm');
  if (dailyForm) dailyForm.onsubmit = event => { event.preventDefault(); buildLegacy(); };
  const downloadDaily = byId('downloadDaily');
  if (downloadDaily) downloadDaily.onclick = () => {
    if (dailyForm.reportValidity()) location.href = '/export/daily-report.csv?' + new URLSearchParams(formData(dailyForm));
  };
  const shiftForm = byId('shiftForm');
  if (shiftForm) shiftForm.onsubmit = event => { event.preventDefault(); buildShift(); };
  const exportShift = byId('exportShift');
  if (exportShift) exportShift.onclick = () => {
    if (!shiftForm.reportValidity()) return;
    const data = formData(shiftForm);
    location.href = '/export/work-logs.csv?' + new URLSearchParams({date_from: data.date, date_to: data.date});
  };

  reports.daily = {buildShift, buildLegacy, showUploaded, showUploadedList};
  window.buildShift = buildShift;
  window.showUploadedReport = showUploaded;
  window.exportUploadedReport = () => { const id = byId('uploadedReport')?.value; if (id) location.href = `/export/uploaded-daily-report.csv?id=${id}`; };
  window.showUploadedReportList = showUploadedList;
  window.exportUploadedReportList = () => { const id = byId('uploadedReportList')?.value; if (id) location.href = `/export/uploaded-daily-report.csv?id=${id}`; };
})();
