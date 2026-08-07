(function () {
  window.ODE = window.ODE || {};
  const reports = (window.ODE.reports = window.ODE.reports || {});
  let logs = [];
  let sort = {key: 'work_date', direction: -1};

  function fillControls() {
    const statuses = reports.form.activeReferences('work_log_status')
      .filter(name => name !== 'Выполнено');
    reports.form.fillSelect(byId('handoverStatus'), statuses, 'Все незавершённые');
  }

  function filteredRows() {
    const query = (byId('handoverSearch')?.value || '').trim().toLocaleLowerCase('ru-RU');
    const dateFrom = byId('handoverFrom')?.value || '';
    const dateTo = byId('handoverTo')?.value || '';
    const status = byId('handoverStatus')?.value || '';
    const rows = logs.filter(row => {
      if (dateFrom && row.work_date < dateFrom) return false;
      if (dateTo && row.work_date > dateTo) return false;
      if (status && row.status !== status) return false;
      if (!query) return true;
      return [
        row.work_date, row.task_source, row.task_number, row.description,
        row.status, row.due_date, row.comment,
      ].join(' ').toLocaleLowerCase('ru-RU').includes(query);
    });
    const {key, direction} = sort;
    return rows.slice().sort((left, right) => {
      const leftValue = String(left[key] || '');
      const rightValue = String(right[key] || '');
      if (leftValue < rightValue) return -direction;
      if (leftValue > rightValue) return direction;
      return (Number(left.id) - Number(right.id)) * direction;
    });
  }

  function actionButtons(row) {
    if (state.current_user.role === 'viewer') return renderElement('span', {text: '—'});
    return renderElement('div', {className: 'uvr-actions', children: [
      // Pass the row itself: the handover list can contain an older unfinished
      // task outside the registry's bounded 1000-row window. Refresh this view
      // after saving so its status/description cannot remain stale.
      renderButton({text: 'Изменить', className: 'button small', onClick: () => window.openUvrEdit(row, load)}),
    ]});
  }

  function render() {
    const body = byId('handoverBody');
    if (!body) return;
    const exportLink = byId('handoverExport');
    if (exportLink) {
      exportLink.href = '/export/handover.xlsx?' + new URLSearchParams({
        search: (byId('handoverSearch')?.value || '').trim(),
        date_from: byId('handoverFrom')?.value || '',
        date_to: byId('handoverTo')?.value || '',
        status: byId('handoverStatus')?.value || '',
      });
    }
    const rows = filteredRows();
    if (!rows.length) {
      body.replaceChildren(renderElement('tr', {children: [
        renderElement('td', {className: 'empty', attrs: {colspan: 8}, text: 'Незавершённых задач нет'}),
      ]}));
      return;
    }
    body.replaceChildren(...rows.map(row => renderElement('tr', {children: [
      renderElement('td', {text: row.work_date}),
      renderElement('td', {text: row.task_source}),
      renderElement('td', {text: row.task_number}),
      renderElement('td', {text: row.description}),
      renderElement('td', {children: [renderElement('span', {className: 'badge', text: row.status})]}),
      renderElement('td', {text: row.due_date || '—'}),
      renderElement('td', {text: row.comment}),
      renderElement('td', {children: [actionButtons(row)]}),
    ]})));
  }

  async function load() {
    try {
      const response = await request('/api/handover');
      logs = response.logs || [];
      fillControls();
      render();
    } catch (error) {
      notify(error.message, true);
    }
  }

  function clearFilters() {
    ['handoverSearch', 'handoverFrom', 'handoverTo', 'handoverStatus']
      .forEach(id => { if (byId(id)) byId(id).value = ''; });
    render();
  }

  ['handoverSearch', 'handoverFrom', 'handoverTo', 'handoverStatus']
    .forEach(id => { const input = byId(id); if (input) input.oninput = input.onchange = render; });
  document.querySelectorAll('#handover .uvr-table th.sortable').forEach(header => {
    header.onclick = () => {
      const key = header.dataset.sort;
      sort.direction = sort.key === key ? -sort.direction : 1;
      sort.key = key;
      render();
    };
  });

  // R1: show the number of tasks awaiting handover on the subtab.
  async function updateBadge() {
    try {
      const response = await request('/api/handover');
      const count = (response.logs || []).length;
      const tab = document.querySelector('.subtab[data-view=handover]');
      if (!tab) return;
      let badge = tab.querySelector('.tab-badge');
      if (!count) { if (badge) badge.remove(); return; }
      if (!badge) { badge = renderElement('span', {className: 'tab-badge'}); tab.append(' ', badge); }
      badge.textContent = String(count);
    } catch (error) { /* badge is best-effort */ }
  }

  reports.handover = {load, render};
  window.buildHandover = () => { load(); updateBadge(); };
  window.updateHandoverBadge = updateBadge;
  window.clearHandoverFilters = clearFilters;
})();
