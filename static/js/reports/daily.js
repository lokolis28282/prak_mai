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

  const SHIFT_COLUMNS = [
    'work_date', 'full_task_name', 'description', 'status', 'section', 'due_date', 'comment',
  ];

  // Render the shift table with per-row actions (view/edit/delete/mark-done),
  // reusing the registry controller so shift entries can be changed or removed
  // in place. Edits/deletes refresh the shift view via buildShift.
  function renderShiftTable(rows) {
    const body = byId('shiftBody');
    if (!body) return;
    const actionsFor = reports.workLogs?.actionsFor;
    if (!rows.length) {
      body.replaceChildren(renderElement('tr', {children: [
        renderElement('td', {className: 'empty', attrs: {colspan: SHIFT_COLUMNS.length + 1}, text: 'За выбранную смену работ не зафиксировано'}),
      ]}));
      return;
    }
    body.replaceChildren(...rows.map(row => {
      const cells = SHIFT_COLUMNS.map(key => renderElement('td', {text: row[key] || ''}));
      cells.push(renderElement('td', {
        children: actionsFor ? [actionsFor(row, buildShift)] : [],
      }));
      return renderElement('tr', {className: row.needs_review ? 'row-review' : '', children: cells});
    }));
  }

  // R9: shift KPI dashboard.
  async function loadStats(date) {
    const host = byId('shiftStats');
    if (!host) return;
    try {
      const s = await request('/api/shift-stats?' + new URLSearchParams({date}));
      const cards = [
        {title: 'Работ за смену', value: s.total},
        {title: 'Выполнено', value: `${s.done} (${s.done_percent}%)`},
        {title: 'Незавершённых', value: s.unfinished},
      ];
      host.replaceChildren(...cards.map(card => renderCard({title: card.title, value: card.value})));
    } catch (error) { notify(error.message, true); }
  }

  async function buildShift() {
    const form = byId('shiftForm');
    if (!form?.reportValidity()) return;
    const data = formData(form);
    try {
      const response = await request('/api/work-logs?' + new URLSearchParams({date_from: data.date, date_to: data.date}));
      setText('shiftEngineer', `${state.current_user.first_name || ''} ${state.current_user.last_name || ''}`.trim());
      renderShiftTable(response.logs || []);
      await loadStats(data.date);
    } catch (error) { notify(error.message, true); }
  }

  // Manual entry writes into the shared work_logs model, so a new record shows
  // up in both the shift view and the full registry at once.
  async function submitShiftLog(form) {
    const submit = form.querySelector('button[type="submit"], button:not([type])');
    try {
      await actionJson({action: 'WORK_LOG', ...reports.form.payload(form)});
      reports.form.resetForm(form);
      notify('Запись добавлена');
      await buildShift();
      if (window.loadWorkLogs && currentMode === 'all') await loadWorkLogs();
    } catch (error) { notify(error.message, true); }
    finally {
      // The global duplicate-submit guard uses a conservative timeout. Reports
      // knows when its complete async flow has finished, so release the form
      // immediately and let the engineer enter the next task without a silent
      // three-second dead period.
      delete form.dataset.submitting;
      if (submit) submit.disabled = false;
    }
  }

  // Inner tab switch: «За смену» (dashboard + day table) vs «Все работы» (registry).
  let currentMode = 'shift';
  function setMode(mode) {
    const paneShift = byId('reportPaneShift');
    const paneAll = byId('reportPaneAll');
    // The panes only exist once the daily section is in the DOM; bail out
    // quietly if this runs before that (e.g. during early navigation).
    if (!paneShift || !paneAll) return;
    currentMode = mode;
    paneShift.hidden = mode !== 'shift';
    paneAll.hidden = mode !== 'all';
    document.querySelectorAll('#daily .report-tab').forEach(tab =>
      tab.classList.toggle('active', tab.dataset.reportTab === mode));
    if (mode === 'shift') buildShift();
    else if (window.loadWorkLogs) loadWorkLogs();
  }

  function open() {
    const shiftLogForm = byId('shiftLogForm');
    if (shiftLogForm) reports.form.initForm(shiftLogForm);
    setMode(currentMode);
  }

  const dailyForm = byId('dailyForm');
  if (dailyForm) dailyForm.onsubmit = event => { event.preventDefault(); buildLegacy(); };
  const downloadDaily = byId('downloadDaily');
  if (downloadDaily) downloadDaily.onclick = () => {
    // The date range covers a report; the XLSX export keys on the start date.
    if (dailyForm.reportValidity()) location.href = '/export/daily-report.xlsx?' + new URLSearchParams({date: formData(dailyForm).date_from});
  };
  const shiftForm = byId('shiftForm');
  if (shiftForm) shiftForm.onsubmit = event => { event.preventDefault(); buildShift(); };
  const shiftLogForm = byId('shiftLogForm');
  if (shiftLogForm) shiftLogForm.onsubmit = event => { event.preventDefault(); submitShiftLog(event.currentTarget); };
  const exportShift = byId('exportShift');
  if (exportShift) exportShift.onclick = () => {
    if (!shiftForm.reportValidity()) return;
    const data = formData(shiftForm);
    // Two-sheet XLSX: «Выполненные работы» + «Передача по смене».
    location.href = '/export/shift-report.xlsx?' + new URLSearchParams({date: data.date});
  };

  reports.daily = {buildShift, buildLegacy, showUploaded, showUploadedList, open, setMode};
  window.buildShift = buildShift;
  window.reportsMode = setMode;
  window.showUploadedReport = showUploaded;
  window.exportUploadedReport = () => { const id = byId('uploadedReport')?.value; if (id) location.href = `/export/uploaded-daily-report.xlsx?id=${id}`; };
  window.showUploadedReportList = showUploadedList;
  window.exportUploadedReportList = () => { const id = byId('uploadedReportList')?.value; if (id) location.href = `/export/uploaded-daily-report.xlsx?id=${id}`; };
})();
