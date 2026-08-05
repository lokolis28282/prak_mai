(function () {
  window.ODE = window.ODE || {};
  const reports = (window.ODE.reports = window.ODE.reports || {});

  const activeReferences = kind => (state.references || [])
    .filter(item => item.kind === kind && item.is_active)
    .map(item => item.name);

  function optionElements(values, placeholder) {
    const options = values.map(value => renderElement('option', {attrs: {value}, text: value}));
    if (placeholder !== undefined) {
      options.unshift(renderElement('option', {attrs: {value: ''}, text: placeholder}));
    }
    return options;
  }

  function fillSelect(select, values, placeholder) {
    if (!select) return;
    const current = select.value;
    select.replaceChildren(...optionElements(values, placeholder));
    if (values.includes(current)) select.value = current;
  }

  // Build the PNR checklist with a "select all" control, a progress meter, and
  // dependency enforcement: a step whose prerequisite is unchecked is disabled
  // and shows the reason. Data stays consistent because the backend re-applies
  // the same order in normalize_pnr_checklist.
  function buildPnrChecklist(form, checked) {
    const container = form.querySelector('.uvr-pnr-checklist');
    if (!container) return;
    const selected = new Set(checked || []);
    const meter = renderElement('div', {className: 'uvr-pnr-progress', children: [
      renderElement('div', {className: 'uvr-pnr-bar', children: [renderElement('span', {attrs: {'data-pnr-fill': ''}})]}),
      renderElement('span', {className: 'uvr-pnr-percent', attrs: {'data-pnr-percent': ''}, text: '0%'}),
    ]});
    const selectAll = renderElement('label', {className: 'uvr-pnr-all', children: [
      renderElement('input', {attrs: {type: 'checkbox'}}),
      renderElement('span', {text: 'Выбрать всё'}),
    ]});
    const items = reports.pnrChecklist.map(step => {
      const input = renderElement('input', {attrs: {type: 'checkbox', value: step.key, 'data-pnr-step': ''}});
      if (selected.has(step.key)) input.checked = true;
      const reason = renderElement('span', {className: 'uvr-pnr-reason', attrs: {'data-pnr-reason': ''}});
      const label = renderElement('label', {className: 'uvr-pnr-item', children: [
        input, renderElement('span', {text: step.label}), reason,
      ]});
      label.dataset.step = step.key;
      label.dataset.requires = step.requires || '';
      return label;
    });
    const allInput = selectAll.querySelector('input');
    const stepInputs = items.map(label => label.querySelector('input'));
    const byKey = key => stepInputs.find(input => input.value === key);

    function refresh() {
      // Enforce prerequisites: disable a step until its prerequisite is checked.
      for (const label of items) {
        const requires = label.dataset.requires;
        const input = label.querySelector('input[data-pnr-step]');
        const reason = label.querySelector('[data-pnr-reason]');
        const unlocked = !requires || (byKey(requires) && byKey(requires).checked);
        input.disabled = !unlocked;
        label.classList.toggle('is-locked', !unlocked);
        if (!unlocked) {
          input.checked = false;  // a locked step cannot stay checked
          reason.textContent = `доступно после: ${reports.pnrLabel(requires)}`;
        } else {
          reason.textContent = '';
        }
      }
      const done = stepInputs.filter(input => input.checked && !input.disabled).length;
      const total = stepInputs.length;
      const percent = total ? Math.round(done * 100 / total) : 0;
      const fill = container.querySelector('[data-pnr-fill]');
      const percentLabel = container.querySelector('[data-pnr-percent]');
      if (fill) fill.style.width = `${percent}%`;
      if (percentLabel) percentLabel.textContent = `${percent}%`;
      allInput.checked = done === total;
    }

    allInput.onchange = () => {
      // Select-all respects the order: check step by step so prerequisites unlock.
      if (allInput.checked) {
        stepInputs.forEach(input => { input.disabled = false; input.checked = true; });
      } else {
        stepInputs.forEach(input => { input.checked = false; });
      }
      refresh();
    };
    stepInputs.forEach(input => { input.onchange = refresh; });
    container.replaceChildren(meter, selectAll, ...items);
    refresh();
  }

  function checkedPnrSteps(form) {
    return [...form.querySelectorAll('.uvr-pnr-checklist input[data-pnr-step]')]
      .filter(input => input.checked && !input.disabled).map(input => input.value);
  }

  let descriptionListSeq = 0;

  // Recent descriptions the engineer used for this source (R5): reused as
  // datalist suggestions when the source has no predefined list.
  function historySuggestions(source) {
    const seen = [];
    for (const row of reports.recentLogs ? reports.recentLogs() : []) {
      if (String(row.task_source || '').toUpperCase() !== String(source || '').toUpperCase()) continue;
      const value = String(row.description || '').trim();
      if (value && !seen.includes(value)) seen.push(value);
      if (seen.length >= 15) break;
    }
    return seen;
  }

  // Apply the per-source description hint: fill the searchable datalist and set
  // the placeholder. Free text always stays allowed.
  function applyDescriptionMode(form, source) {
    const input = form.querySelector('.uvr-description-input');
    const datalist = form.querySelector('.uvr-description-options');
    if (!input || !datalist) return;
    const mode = reports.descriptionMode(source);
    const options = (mode && mode.options) || historySuggestions(source);
    if (options.length) {
      if (!datalist.id) datalist.id = `descOptions${++descriptionListSeq}`;
      datalist.replaceChildren(...options.map(value => renderElement('option', {attrs: {value}})));
      input.setAttribute('list', datalist.id);
    } else {
      datalist.replaceChildren();
      input.setAttribute('list', '');
    }
    input.placeholder = (mode && mode.placeholder) || 'Описание работ';
  }

  // Toggle description field vs PNR checklist based on the selected source.
  function applySourceMode(form) {
    const source = form.querySelector('[name=task_source]')?.value || '';
    const pnr = reports.isPnr(source);
    const descriptionField = form.querySelector('.uvr-description-field');
    const pnrField = form.querySelector('.uvr-pnr-field');
    const description = form.querySelector('[name=description]');
    if (descriptionField) descriptionField.hidden = pnr;
    if (description) description.required = !pnr;
    if (!pnr) applyDescriptionMode(form, source);
    if (pnrField) {
      pnrField.hidden = !pnr;
      if (pnr && !pnrField.dataset.built) {
        buildPnrChecklist(form, []);
        pnrField.dataset.built = '1';
      }
    }
    // Status is derived for PNR; lock the control so the value is unambiguous.
    const status = form.querySelector('[name=status]');
    if (status) status.disabled = pnr;
  }

  // Populate a УВР-style form's selects and wire the source-mode toggle.
  function initForm(form) {
    if (!form) return;
    fillSelect(form.querySelector('[name=task_source]'), activeReferences('task_source'), 'Источник');
    fillSelect(form.querySelector('[name=status]'), activeReferences('work_log_status'), undefined);
    fillSelect(form.querySelector('[name=section]'), activeReferences('work_log_section'), 'Выберите раздел');
    const source = form.querySelector('[name=task_source]');
    if (source && !source.dataset.bound) {
      source.addEventListener('change', () => applySourceMode(form));
      source.dataset.bound = '1';
    }
    applySourceMode(form);
  }

  // Assemble the action payload from a УВР-style form. For PNR the description
  // and status are left to the backend, which derives them from the checklist.
  function payload(form, extra) {
    const data = formData(form);
    const source = data.task_source || '';
    const base = {
      work_date: data.work_date, task_source: source, task_number: data.task_number || '',
      task_type: data.task_type || '', section: data.section, due_date: data.due_date || '',
      comment: data.comment || '', ...extra,
    };
    if (reports.isPnr(source)) {
      base.pnr_checklist = checkedPnrSteps(form);
    } else {
      base.description = data.description || '';
      base.status = data.status;
    }
    return base;
  }

  function resetForm(form) {
    ['description', 'task_number', 'comment'].forEach(name => {
      const field = form.querySelector(`[name=${name}]`);
      if (field) field.value = '';
    });
    const pnrField = form.querySelector('.uvr-pnr-field');
    if (pnrField) { delete pnrField.dataset.built; if (!pnrField.hidden) buildPnrChecklist(form, []); }
  }

  reports.form = {
    activeReferences, fillSelect, initForm, applySourceMode,
    buildPnrChecklist, checkedPnrSteps, payload, resetForm,
  };
})();
