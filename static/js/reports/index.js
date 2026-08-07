(function () {
  window.ODE = window.ODE || {};
  const reports = (window.ODE.reports = window.ODE.reports || {});

  const routes = [
    ['daily', 'Отчет за смену'],
    ['handover', 'Передача по смене'],
    ['weekly', 'Отчет за неделю'],
    ['journal', 'Складские операции'],
  ];
  sections.reports = routes;
  // Compatibility alias for saved links that still point at the УВР registry,
  // which now lives inside the shift report tab.
  sections.works = [['daily', 'Отчет за смену']];
  reports.routes = routes.map(([route]) => route);
  reports.ready = true;

  // PNR checklist steps mirror inventory/reports/validators.PNR_CHECKLIST.
  // Keys must stay in sync with the backend, which derives description/status.
  reports.PNR_SOURCE = 'PNR';
  reports.pnrChecklist = [
    {key: 'servers', label: 'Установка оборудования в стойки', requires: null},
    {key: 'power', label: 'Подключение питания', requires: null},
    {key: 'transceivers', label: 'Установка трансиверов', requires: null},
    {key: 'marking', label: 'Маркировка кабеля', requires: null},
    {key: 'laying', label: 'Прокладка кабеля', requires: 'marking'},
    {key: 'switching', label: 'Коммутация кабельных систем', requires: 'laying'},
  ];
  reports.pnrLabel = key => (reports.pnrChecklist.find(step => step.key === key) || {}).label || key;
  reports.isPnr = source => String(source || '').trim().toUpperCase() === reports.PNR_SOURCE;

  // Per-source hints for the «Описание работ» field. `options` (if present) fill
  // a searchable datalist while still allowing free text; `placeholder` sets the
  // input hint. Keyed by the uppercased task source.
  reports.descriptionModes = {
    'ЗНР': {
      placeholder: 'Выберите или введите описание',
      options: [
        'Коммутация оборудования', 'Декоммутация оборудования',
        'Подготовка отправки', 'Установка оборудования', 'Конфигурирование серверов',
      ],
    },
    'OUTLOOK': {placeholder: 'Введите тему письма'},
    'ИЗМ': {placeholder: 'Введите номер ЗНР'},
    'ИНЦ': {
      placeholder: 'Выберите или введите инцидент',
      options: [
        'Link down', 'has been restarted (uptime < 10m)', 'Memory : Status is not OK',
        'System status is in critical state', 'BMC: Health is in critical state more than 15m',
        'BMC: No health data more than 10m', 'Host is unavailable by ICMP more than 5m',
        'Host is unavailable by SNMP more than 15m',
      ],
    },
  };
  reports.descriptionMode = source => reports.descriptionModes[String(source || '').trim().toUpperCase()] || null;

  reports.WORK_TABLE_COLUMNS = [
    'work_date', 'full_task_name', 'description', 'status', 'section', 'due_date', 'comment',
  ];

  reports.renderWorkTable = function (bodyId, rows, emptyText, columns) {
    const body = byId(bodyId);
    if (!body) return;
    const keys = columns || reports.WORK_TABLE_COLUMNS;
    if (!rows.length) {
      body.replaceChildren(renderElement('tr', {
        children: [renderElement('td', {className: 'empty', attrs: {colspan: keys.length}, text: emptyText})],
      }));
      return;
    }
    body.replaceChildren(...rows.map(row => renderElement('tr', {
      className: row.needs_review ? 'row-review' : '',
      children: keys.map(key => renderElement('td', {text: row[key] || ''})),
    })));
  };

  window.openReportsHub = function () {
    // The registry now lives inside the shift report screen. Open that real
    // route and select its «Все работы» pane instead of targeting the removed
    // legacy `#worklogs` view (which left the Reports workspace blank).
    openTask('reports', 'daily');
    window.reportsMode?.('all');
  };
})();
