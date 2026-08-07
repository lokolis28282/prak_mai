(function () {
  window.ODE = window.ODE || {};
  const reports = (window.ODE.reports = window.ODE.reports || {});
  let logs = [];
  let meta = {total: 0, truncated: false, limit: 1000};
  let sort = {key: 'work_date', direction: -1};
  const selected = new Set();
  const PAGE_SIZE = 25;
  let page = 1;

  const form = () => reports.form;
  const today = () => { const d = new Date(); const p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; };
  const isOverdue = row => row.due_date && row.due_date < today() && row.status !== 'Выполнено';

  function fillControls() {
    form().fillSelect(byId('uvrFilterStatus'), form().activeReferences('work_log_status'), 'Все статусы');
    const sections = [...new Set([
      ...form().activeReferences('work_log_section'), ...logs.map(row => row.section).filter(Boolean),
    ])].sort((left, right) => left.localeCompare(right, 'ru'));
    form().fillSelect(byId('uvrFilterSection'), sections, 'Все разделы');
    form().fillSelect(byId('uvrBulkSection'), form().activeReferences('work_log_section'), 'Раздел');
  }

  // All filters are sent to the server so matches beyond the 1000-row safety
  // window are not silently omitted. The local predicates remain defensive.
  function queryParams() {
    return {
      date_from: byId('uvrFilterFrom')?.value || '',
      date_to: byId('uvrFilterTo')?.value || '',
      search: (byId('uvrSearch')?.value || '').trim(),
      status: byId('uvrFilterStatus')?.value || '',
      section: byId('uvrFilterSection')?.value || '',
      needs_review: byId('uvrReviewOnly')?.checked ? '1' : '',
    };
  }

  function visibleRows() {
    const section = byId('uvrFilterSection')?.value || '';
    const status = byId('uvrFilterStatus')?.value || '';
    const rows = logs.filter(row =>
      (!section || row.section === section) && (!status || row.status === status));
    const {key, direction} = sort;
    return rows.sort((left, right) => {
      const leftValue = String(left[key] || '');
      const rightValue = String(right[key] || '');
      if (leftValue < rightValue) return -direction;
      if (leftValue > rightValue) return direction;
      return (Number(left.id) - Number(right.id)) * direction;
    });
  }

  // Action cell for a work-log row: «Изменить» and «Удалить» (viewers get a
  // read-only «Просмотр»). `onChange` runs after a successful edit/delete so the
  // calling view refreshes itself — the registry passes `load`, the shift view
  // passes `buildShift`. The row object is captured directly, so this works for
  // rows that are not in the registry's own `logs` array (e.g. the shift table).
  function actionButtons(row, onChange) {
    const refresh = onChange || load;
    // Viewers cannot edit or delete, so they keep a read-only «Просмотр».
    if (state.current_user.role === 'viewer') {
      return renderElement('div', {className: 'uvr-actions', children: [
        renderButton({text: 'Просмотр', className: 'button small', onClick: () => openView(row)}),
      ]});
    }
    return renderElement('div', {className: 'uvr-actions', children: [
      renderButton({text: 'Изменить', className: 'button small', onClick: () => openEdit(row, refresh)}),
      renderButton({text: 'Удалить', className: 'button small danger', onClick: () => deleteLog(row, refresh)}),
    ]});
  }

  function render() {
    const body = byId('workLogBody');
    if (!body) return;
    const rows = visibleRows();
    // Page navigation over the filtered set: page 1 = rows 1–25, page 2 = 26–50…
    const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    if (page > pages) page = pages;
    if (page < 1) page = 1;
    const start = (page - 1) * PAGE_SIZE;
    const pageRows = rows.slice(start, start + PAGE_SIZE);
    updateCount(rows.length, start, pageRows.length);
    renderPager(rows.length, pages);
    if (!rows.length) {
      body.replaceChildren(renderElement('tr', {children: [
        renderElement('td', {className: 'empty', attrs: {colspan: 9}, text: 'Нет записей'}),
      ]}));
      syncSelectionUi();
      return;
    }
    body.replaceChildren(...pageRows.map(row => {
      const check = renderElement('input', {attrs: {type: 'checkbox'}});
      check.checked = selected.has(row.id);
      check.onchange = () => { check.checked ? selected.add(row.id) : selected.delete(row.id); syncSelectionUi(); };
      const section = renderElement('td', {children: [renderElement('span', {text: row.section || ''})]});
      if (row.needs_review) {
        section.append(' ', renderElement('span', {
          className: 'badge warn', attrs: {title: 'Импортировано из старого файла, требует проверки'}, text: 'проверить',
        }));
      }
      const classes = [row.needs_review ? 'row-review' : '', isOverdue(row) ? 'row-overdue' : ''].filter(Boolean).join(' ');
      const due = renderElement('td', {text: row.due_date || '—'});
      if (isOverdue(row)) due.classList.add('cell-overdue');
      return renderElement('tr', {className: classes, children: [
        renderElement('td', {
          className: 'uvr-check-col',
          attrs: {hidden: state.current_user.role === 'viewer'},
          children: [check],
        }),
        renderElement('td', {text: row.work_date}),
        renderElement('td', {text: row.full_task_name}),
        renderElement('td', {text: row.description}),
        renderElement('td', {children: [renderElement('span', {className: 'badge', text: row.status})]}),
        section,
        due,
        renderElement('td', {text: row.comment}),
        renderElement('td', {children: [actionButtons(row)]}),
      ]});
    }));
    syncSelectionUi();
  }

  function updateCount(filtered, start, shownOnPage) {
    const el = byId('uvrCount');
    if (!el) return;
    let text;
    if (!filtered) {
      text = `Показано 0 из ${meta.total}`;
    } else {
      text = `Показаны ${start + 1}–${start + shownOnPage} из ${filtered}`;
    }
    if (meta.truncated) text += ` (загружены первые ${meta.limit}; уточните фильтр)`;
    el.textContent = text;
  }

  function goToPage(next) {
    page = next;
    render();
    const pane = byId('reportPaneAll');
    if (pane) pane.querySelector('.uvr-table')?.scrollIntoView({block: 'nearest'});
  }

  function renderPager(total, pages) {
    const host = byId('uvrPager');
    if (!host) return;
    if (pages <= 1) { host.replaceChildren(); return; }
    const btn = (label, targetPage, disabled, active) => renderButton({
      text: label,
      className: `button small${active ? ' primary' : ''}`,
      disabled,
      onClick: () => goToPage(targetPage),
    });
    const children = [btn('←', page - 1, page <= 1, false)];
    // Compact window of page numbers around the current page.
    const windowSize = 2;
    let from = Math.max(1, page - windowSize);
    let to = Math.min(pages, page + windowSize);
    if (from > 1) children.push(btn('1', 1, false, page === 1));
    if (from > 2) children.push(renderElement('span', {className: 'uvr-pager-gap', text: '…'}));
    for (let p = from; p <= to; p += 1) children.push(btn(String(p), p, false, p === page));
    if (to < pages - 1) children.push(renderElement('span', {className: 'uvr-pager-gap', text: '…'}));
    if (to < pages) children.push(btn(String(pages), pages, false, page === pages));
    children.push(btn('→', page + 1, page >= pages, false));
    host.replaceChildren(...children);
  }

  function syncSelectionUi() {
    const bulk = byId('uvrBulk');
    if (bulk) bulk.hidden = selected.size === 0;
    const count = byId('uvrBulkCount');
    if (count) count.textContent = `Выбрано: ${selected.size}`;
    const all = byId('uvrSelectAll');
    if (all) all.checked = logs.length > 0 && logs.every(row => selected.has(row.id));
  }

  async function load() {
    try {
      const response = await request('/api/work-logs-page?' + new URLSearchParams(queryParams()));
      logs = response.logs || [];
      meta = {total: response.total || 0, truncated: !!response.truncated, limit: response.limit || 1000};
      selected.clear();
      page = 1;
      fillControls();
      render();
      const exportLink = byId('exportWorkLogs');
      if (exportLink) exportLink.href = '/export/work-logs.xlsx?' + new URLSearchParams(queryParams());
    } catch (error) {
      notify(error.message, true);
    }
  }

  async function deleteLog(rowOrId, onChange) {
    const row = resolveRow(rowOrId);
    const id = row ? row.id : rowOrId;
    const name = row?.full_task_name ? `«${row.full_task_name}»` : 'эту запись';
    const ok = await confirmDialog({
      title: 'Удалить запись',
      message: `Удалить ${name}? Действие необратимо.`,
      confirmText: 'Удалить',
      danger: true,
    });
    if (!ok) return;
    try {
      await actionJson({action: 'DELETE_WORK_LOG', id});
      notify('Запись удалена');
      await (onChange || load)();
    } catch (error) { notify(error.message, true); }
  }

  function selectOptions(values, selectedValue) {
    return values.map(value => `<option${value === selectedValue ? ' selected' : ''}>${esc(value)}</option>`).join('');
  }

  const infoRow = (label, value) => value ? `<div class="uvr-view-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>` : '';

  // Accept either a row object (shift view passes its own rows) or an id that is
  // resolved against the registry's loaded set.
  function resolveRow(rowOrId) {
    if (rowOrId && typeof rowOrId === 'object') return rowOrId;
    return logs.find(item => Number(item.id) === Number(rowOrId)) || null;
  }

  // R4: read-only view — see the full record (incl. PNR steps) without editing.
  function openView(rowOrId) {
    const row = resolveRow(rowOrId);
    if (!row) return;
    let pnr = '';
    if (reports.isPnr(row.task_source)) {
      const steps = String(row.pnr_checklist || '').split(',').map(s => s.trim()).filter(Boolean);
      const list = reports.pnrChecklist.map(step =>
        `<li class="${steps.includes(step.key) ? 'done' : ''}">${steps.includes(step.key) ? '✓' : '—'} ${esc(step.label)}</li>`).join('');
      const percent = Math.round(steps.length * 100 / reports.pnrChecklist.length);
      pnr = `<div class="uvr-view-row"><span>PNR</span><strong>${percent}%</strong></div><ul class="uvr-view-pnr">${list}</ul>`;
    }
    const modal = document.createElement('div');
    modal.className = 'modal show';
    modal.innerHTML = `<div class="modal-card"><div class="modal-head"><h3>Запись: ${esc(row.full_task_name)}</h3><button class="button" type="button" data-close>Закрыть</button></div><div class="uvr-view">${infoRow('Дата', row.work_date)}${infoRow('Источник', row.task_source)}${infoRow('Номер', row.task_number)}${infoRow('Описание', row.description)}${infoRow('Статус', row.status)}${infoRow('Раздел', row.section)}${infoRow('Срок', row.due_date)}${infoRow('Комментарий', row.comment)}${pnr}</div><div class="actions">${state.current_user.role !== 'viewer' ? '<button class="button primary" type="button" data-edit>Изменить</button>' : ''}<button class="button" type="button" data-close>Закрыть</button></div></div>`;
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-close]').forEach(button => button.onclick = () => modal.remove());
    const edit = modal.querySelector('[data-edit]');
    if (edit) edit.onclick = () => { modal.remove(); openEdit(row); };
  }

  function openEdit(rowOrId, onChange) {
    const row = resolveRow(rowOrId);
    if (!row) return;
    const refresh = onChange || load;
    const sources = form().activeReferences('task_source');
    if (row.task_source && !sources.includes(row.task_source)) sources.unshift(row.task_source);
    const sections = form().activeReferences('work_log_section');
    if (row.section && !sections.includes(row.section)) sections.unshift(row.section);
    const modal = document.createElement('div');
    modal.className = 'modal show';
    modal.innerHTML = `<div class="modal-card"><div class="modal-head"><h3>Изменить запись</h3><button class="button" type="button" data-close>Закрыть</button></div><form id="uvrEditForm" class="form uvr-form" data-uvr-form><div class="uvr-form-grid"><div><label>Дата</label><input name="work_date" type="date" value="${esc(row.work_date)}" required></div><div><label>Источник задачи</label><select name="task_source" required>${selectOptions(sources, row.task_source)}</select></div><div><label>Номер задачи</label><input name="task_number" value="${esc(row.task_number)}"></div><div class="uvr-desc-cell"><label>Описание работ</label><input name="description" class="uvr-description-input" list="" autocomplete="off" value="${esc(row.description)}"><datalist class="uvr-description-options"></datalist></div><div><label>Раздел</label><select name="section">${selectOptions(sections, row.section)}</select></div><div><label>Статус</label><select name="status" required>${selectOptions(form().activeReferences('work_log_status'), row.status)}</select></div><div><label>Срок выполнения</label><input name="due_date" type="date" value="${esc(row.due_date || '')}" required></div></div><div class="uvr-pnr-field" hidden><label>Выполненные работы (PNR)</label><div class="uvr-pnr-checklist"></div></div><label>Комментарий</label><textarea name="comment">${esc(row.comment)}</textarea><div class="actions"><button class="button primary">Сохранить</button><button class="button" type="button" data-close>Отмена</button></div></form></div>`;
    document.body.appendChild(modal);
    const editForm = modal.querySelector('#uvrEditForm');
    const checked = String(row.pnr_checklist || '').split(',').map(part => part.trim()).filter(Boolean);
    editForm.querySelector('[name=task_source]').addEventListener('change', () => form().applySourceMode(editForm));
    form().applySourceMode(editForm);
    if (reports.isPnr(row.task_source)) form().buildPnrChecklist(editForm, checked);
    modal.querySelectorAll('[data-close]').forEach(button => button.onclick = () => modal.remove());
    editForm.onsubmit = async event => {
      event.preventDefault();
      try {
        await actionJson({action: 'UPDATE_WORK_LOG', id: row.id, ...form().payload(editForm)});
        modal.remove();
        notify('Запись обновлена');
        await refresh();
      } catch (error) { notify(error.message, true); }
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
        (preview.error_count ? ` Ошибок: ${preview.error_count}.` : '');
      const ok = await confirmDialog({
        title: 'Импорт из Excel', message, confirmText: 'Импортировать',
      });
      if (ok) {
        const result = await actionJson({action: 'CONFIRM_IMPORT_PREVIEW', kind: 'work_logs', preview_id: preview.preview_id});
        notify(`Импортировано строк: ${result.imported}`);
        await load();
      }
    } catch (error) {
      notify(error.message, true);
    } finally {
      input.value = '';
    }
  }

  // R8: bulk-assign a section to the checked rows and clear their review flag.
  async function bulkAssign() {
    const section = byId('uvrBulkSection')?.value;
    if (!section) { notify('Выберите раздел', true); return; }
    if (!selected.size) return;
    try {
      const result = await actionJson({action: 'ASSIGN_SECTION', ids: [...selected], section});
      notify(`Обновлено записей: ${result.updated}`);
      await load();
    } catch (error) { notify(error.message, true); }
  }

  function clearSelection() { selected.clear(); render(); }

  function clearFilters() {
    ['uvrSearch', 'uvrFilterFrom', 'uvrFilterTo', 'uvrFilterStatus', 'uvrFilterSection']
      .forEach(id => { if (byId(id)) byId(id).value = ''; });
    const review = byId('uvrReviewOnly');
    if (review) review.checked = false;
    load();
  }

  let searchTimer = null;
  // Server-side filters re-fetch the bounded result set.
  ['uvrFilterFrom', 'uvrFilterTo', 'uvrReviewOnly', 'uvrFilterSection', 'uvrFilterStatus'].forEach(id => {
    const input = byId(id);
    if (input) input.onchange = load;
  });
  const searchInput = byId('uvrSearch');
  if (searchInput) searchInput.oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(load, 300); };
  // Client-side filter/sort changes shrink or reorder the set, so jump back to
  // the first page before re-rendering.
  const renderFromFirstPage = () => { page = 1; render(); };
  const csv = byId('workLogsCsv');
  if (csv) csv.onchange = event => previewCsv(event.currentTarget);
  const xlsx = byId('workLogsXlsx');
  if (xlsx) xlsx.onchange = () => importXlsx(xlsx);
  const selectAll = byId('uvrSelectAll');
  if (selectAll) selectAll.onchange = () => {
    if (selectAll.checked) logs.forEach(row => selected.add(row.id));
    else selected.clear();
    render();
  };
  document.querySelectorAll('#reportPaneAll .uvr-table th.sortable').forEach(header => {
    header.onclick = () => {
      const key = header.dataset.sort;
      sort.direction = sort.key === key ? -sort.direction : 1;
      sort.key = key;
      renderFromFirstPage();
    };
  });

  reports.workLogs = {load, render, fillControls, actionsFor: actionButtons};
  reports.recentLogs = () => logs;
  window.loadWorkLogs = load;
  window.uvrFillControls = fillControls;
  window.clearUvrFilters = clearFilters;
  window.openUvrEdit = openEdit;
  window.deleteUvr = deleteLog;
  window.uvrBulkAssign = bulkAssign;
  window.uvrClearSelection = clearSelection;
})();
