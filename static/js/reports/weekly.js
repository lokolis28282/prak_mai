(function () {
  window.ODE = window.ODE || {};
  const reports = (window.ODE.reports = window.ODE.reports || {});

  async function buildLegacy() {
    const form = byId('weeklyForm');
    const query = new URLSearchParams(formData(form));
    try {
      const response = await request('/api/weekly-report?' + query);
      const labels = {
        work_logs: 'Логи работ', receipts: 'Приходы', received_quantity: 'Принято',
        issues: 'Расходы', issued_quantity: 'Списано', cable_received: 'Кабеля принято',
        cable_issued: 'Кабеля списано', problem_rows: 'Проблемные строки',
        loaded_deliveries: 'Загруженные поставки', accepted_delivery_items: 'Принятые позиции поставок',
        delivery_problem_rows: 'Проблемные строки поставок',
      };
      byId('weeklyCards').replaceChildren(...Object.entries(response.summary || {}).map(([key, value]) =>
        renderCard({title: labels[key] || key, value: Number(value).toLocaleString('ru-RU')})
      ));
      const renderRows = (id, rows) => {
        byId(id).innerHTML = rows.map(row => `<tr><td>${esc(row.name)}</td><td>${Number(row.received).toLocaleString('ru-RU')}</td><td>${Number(row.issued).toLocaleString('ru-RU')}</td></tr>`).join('') || '<tr><td class="empty" colspan="3">Нет данных</td></tr>';
      };
      renderRows('weeklyProjects', response.projects || []);
      renderRows('weeklyTypes', response.types || []);
    } catch (error) { notify(error.message, true); }
  }

  async function buildWeek() {
    const form = byId('weekReportForm');
    if (!form?.reportValidity()) return;
    const data = formData(form);
    try {
      const response = await request('/api/work-logs?' + new URLSearchParams({date_from: data.date_from, date_to: data.date_to}));
      setText('weekEngineer', `${state.current_user.first_name || ''} ${state.current_user.last_name || ''}`.trim());
      reports.renderWorkTable('weekBody', response.logs || [], 'За выбранный период работ не зафиксировано');
    } catch (error) { notify(error.message, true); }
  }

  const weeklyForm = byId('weeklyForm');
  if (weeklyForm) weeklyForm.onsubmit = event => { event.preventDefault(); buildLegacy(); };
  const downloadWeekly = byId('downloadWeekly');
  if (downloadWeekly) downloadWeekly.onclick = () => {
    if (weeklyForm.reportValidity()) location.href = '/export/weekly-report.csv?' + new URLSearchParams(formData(weeklyForm));
  };
  const reportForm = byId('weekReportForm');
  if (reportForm) reportForm.onsubmit = event => { event.preventDefault(); buildWeek(); };
  const exportWeek = byId('exportWeek');
  if (exportWeek) exportWeek.onclick = () => {
    if (!reportForm.reportValidity()) return;
    const data = formData(reportForm);
    location.href = '/export/work-logs.csv?' + new URLSearchParams({date_from: data.date_from, date_to: data.date_to});
  };

  reports.weekly = {buildWeek, buildLegacy};
  window.buildWeek = buildWeek;
})();
