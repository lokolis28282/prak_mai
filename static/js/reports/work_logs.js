(function () {
  window.ODE = window.ODE || {};
  const reports = (window.ODE.reports = window.ODE.reports || {});
  let logs = [];
  let sort = {key: 'work_date', direction: -1};

  const activeReferences = kind => (state.references || [])
    .filter(item => item.kind === kind && item.is_active)
    .map(item => item.name);

  function taskTemplates() {
    return activeReferences('task_source');
  }

  function splitTaskName(raw) {
    const value = String(raw || '').trim();
    for (const template of taskTemplates()) {
      if (value === template) return {task_source: template, task_number: ''};
      for (const separator of ['-', ': ', ' ']) {
        const prefix = template + separator;
        if (value.toLowerCase().startsWith(prefix.toLowerCase())) {
          return {task_source: template, task_number: value.slice(prefix.length).trim()};
        }
      }
      if (value.toLowerCase().startsWith(template.toLowerCase())) {
        return {task_source: template, task_number: value.slice(template.length).trim()};
      }
    }
    return {task_source: 'Не указан', task_number: value};
  }

  function sectionReferences() {
    return activeReferences('work_log_section');
  }

  function replaceOptions(select, values, placeholder) {
    if (!select) return;
    const current = select.value;
    select.replaceChildren(
      renderElement('option', {attrs: {value: ''}, text: placeholder}),
      ...values.map(value => renderElement('option', {attrs: {value}, text: value})),
    );
    if (values.includes(current)) select.value = current;
  }

  function fillControls() {
    const templates = byId('uvrTaskTemplates');
    if (templates) {
      templates.replaceChildren(...taskTemplates().map(value =>
        renderElement('option', {attrs: {value}})
      ));
    }
    replaceOptions(byId('uvrSection'), sectionReferences(), 'Выберите раздел');
    replaceOptions(byId('uvrFilterStatus'), activeReferences('work_log_status'), 'Все статусы');
    const sections = [...new Set([
      ...sectionReferences(), ...logs.map(row => row.section).filter(Boolean),
    ])].sort((left, right) => left.localeCompare(right, 'ru'));
    replaceOptions(byId('uvrFilterSection'), sections, 'Все разделы');
  }

  function filteredRows() {
    const query = (byId('uvrSearch')?.value || '').trim().toLocaleLowerCase('ru-RU');
    const dateFrom = byId('uvrFilterFrom')?.value || '';
    const dateTo = byId('uvrFilterTo')?.value || '';
    const status = byId('uvrFilterStatus')?.value || '';
    const section = byId('uvrFilterSection')?.value || '';
    const rows = logs.filter(row => {
      if (dateFrom && row.work_date < dateFrom) return false;
      if (dateTo && row.work_date > dateTo) return false;
      if (status && row.status !== status) return false;
      if (section && row.section !== section) return false;
      if (!query) return true;
      return [
        row.work_date, row.full_task_name, row.description, row.status,
        row.section, row.task_type, row.comment,
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
      renderButton({text: 'Изменить', className: 'button small', onClick: () => openEdit(row.id)}),
      renderButton({text: 'Удалить', className: 'button small', onClick: () => deleteLog(row.id)}),
    ]});
  }

  function render() {
    const body = byId('workLogBody');
    if (!body) return;
    const rows = filteredRows();
    if (!rows.length) {
      body.replaceChildren(renderElement('tr', {children: [
        renderElement('td', {className: 'empty', attrs: {colspan: 8}, text: 'Нет записей'}),
      ]}));
      return;
    }
    body.replaceChildren(...rows.map(row => {
      const section = renderElement('td', {children: [renderElement('span', {text: row.section || ''})]});
      if (row.needs_review) {
        section.append(' ', renderElement('span', {
          className: 'badge warn', attrs: {title: 'Импортировано из старого файла, требует проверки'}, text: 'проверить',
        }));
      }
      return renderElement('tr', {className: row.needs_review ? 'row-review' : '', children: [
        renderElement('td', {text: row.work_date}),
        renderElement('td', {text: row.full_task_name}),
        renderElement('td', {text: row.description}),
        renderElement('td', {children: [renderElement('span', {className: 'badge', text: row.status})]}),
        section,
        renderElement('td', {text: row.task_type}),
        renderElement('td', {text: row.comment}),
        renderElement('td', {children: [actionButtons(row)]}),
      ]});
    }));
  }

  async function load() {
    try {
      const response = await request('/api/work-logs');
      logs = response.logs || [];
      fillControls();
      render();
      const exportLink = byId('exportWorkLogs');
      if (exportLink) exportLink.href = '/export/work-logs.csv';
    } catch (error) {
      notify(error.message, true);
    }
  }

  async function submit(form) {
    const data = formData(form);
    const task = splitTaskName(data.task_name);
    try {
      await actionJson({
        action: 'WORK_LOG', work_date: data.work_date,
        task_source: task.task_source, task_number: task.task_number,
        description: data.description, status: data.status,
        section: data.section, task_type: data.task_type, comment: data.comment,
      });
      form.querySelector('[name=description]').value = '';
      form.querySelector('[name=comment]').value = '';
      form.querySelector('[name=task_name]').value = '';
      notify('Запись добавлена');
      await load();
      await loadAll();
    } catch (error) {
      notify(error.message, true);
    }
  }

  async function deleteLog(id) {
    if (!confirm('Удалить запись УВР?')) return;
    try {
      await actionJson({action: 'DELETE_WORK_LOG', id});
      notify('Запись удалена');
      await load();
    } catch (error) {
      notify(error.message, true);
    }
  }

  function selectOptions(values, selected) {
    return values.map(value =>
      `<option${value === selected ? ' selected' : ''}>${esc(value)}</option>`
    ).join('');
  }

  function openEdit(id) {
    const row = logs.find(item => Number(item.id) === Number(id));
    if (!row) return;
    const sections = sectionReferences();
    if (row.section && !sections.includes(row.section)) sections.unshift(row.section);
    const modal = document.createElement('div');
    modal.className = 'modal show';
    modal.innerHTML = `<div class="modal-card"><div class="modal-head"><h3>Изменить запись УВР</h3><button class="button" type="button" data-close>Закрыть</button></div><form id="uvrEditForm" class="form"><label>Дата</label><input name="work_date" type="date" value="${esc(row.work_date)}" required><label>Имя задачи</label><input name="task_name" value="${esc(row.full_task_name)}" list="uvrTaskTemplates" required><label>Описание работ</label><textarea name="description" required>${esc(row.description)}</textarea><label>Статус</label><select name="status" required>${selectOptions(activeReferences('work_log_status'), row.status)}</select><label>Раздел</label><select name="section" required>${selectOptions(sections, row.section)}</select><label>Тип</label><select name="task_type" required>${selectOptions(activeReferences('task_type'), row.task_type)}</select><label>Комментарий</label><textarea name="comment">${esc(row.comment)}</textarea><div class="actions"><button class="button primary">Сохранить</button><button class="button" type="button" data-close>Отмена</button></div></form></div>`;
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-close]').forEach(button => button.onclick = () => modal.remove());
    modal.querySelector('#uvrEditForm').onsubmit = async event => {
      event.preventDefault();
      const data = formData(event.currentTarget);
      const task = splitTaskName(data.task_name);
      try {
        await actionJson({
          action: 'UPDATE_WORK_LOG', id, work_date: data.work_date,
          task_source: task.task_source, task_number: task.task_number,
          description: data.description, status: data.status,
          section: data.section, task_type: data.task_type, comment: data.comment,
        });
        modal.remove();
        notify('Запись обновлена');
        await load();
      } catch (error) {
        notify(error.message, true);
      }
    };
  }

  async function importXlsx(input) {
    const file = input.files[0];
    if (!file) return;
    try {
      const preview = await request('/api/preview-xlsx?sheet=' + encodeURIComponent('Логи'), {
        method: 'POST',
        headers: {'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name)},
        body: file,
      });
      const message = `Готово к импорту: ${preview.valid} из ${preview.total} строк.` +
        (preview.error_count ? ` Ошибок: ${preview.error_count}.` : '') + ' Импортировать?';
      if (confirm(message)) {
        const result = await actionJson({
          action: 'CONFIRM_IMPORT_PREVIEW', kind: 'work_logs', preview_id: preview.preview_id,
        });
        notify(`Импортировано строк: ${result.imported}`);
        await load();
      }
    } catch (error) {
      notify(error.message, true);
    } finally {
      input.value = '';
    }
  }

  function clearFilters() {
    ['uvrSearch', 'uvrFilterFrom', 'uvrFilterTo', 'uvrFilterStatus', 'uvrFilterSection']
      .forEach(id => { if (byId(id)) byId(id).value = ''; });
    render();
  }

  const form = byId('workLogForm');
  if (form) form.onsubmit = event => { event.preventDefault(); submit(event.currentTarget); };
  const csv = byId('workLogsCsv');
  if (csv) csv.onchange = event => previewCsv(event.currentTarget);
  const xlsx = byId('workLogsXlsx');
  if (xlsx) xlsx.onchange = () => importXlsx(xlsx);
  ['uvrSearch', 'uvrFilterFrom', 'uvrFilterTo', 'uvrFilterStatus', 'uvrFilterSection']
    .forEach(id => { const input = byId(id); if (input) input.oninput = input.onchange = render; });
  document.querySelectorAll('.uvr-table th.sortable').forEach(header => {
    header.onclick = () => {
      const key = header.dataset.sort;
      sort.direction = sort.key === key ? -sort.direction : 1;
      sort.key = key;
      render();
    };
  });

  reports.workLogs = {load, render, fillControls, splitTaskName};
  window.loadWorkLogs = load;
  window.uvrFillControls = fillControls;
  window.clearUvrFilters = clearFilters;
  window.openUvrEdit = openEdit;
  window.deleteUvr = deleteLog;
})();
