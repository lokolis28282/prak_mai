(function () {
  window.ODE = window.ODE || {};
  const reports = (window.ODE.reports = window.ODE.reports || {});

  const routes = [
    ['worklogs', 'УВР'],
    ['daily', 'Отчет за смену'],
    ['weekly', 'Отчет за неделю'],
    ['journal', 'Складские операции'],
  ];
  sections.reports = routes;
  // Compatibility alias for saved links from the former standalone Works card.
  sections.works = [['worklogs', 'УВР']];
  reports.routes = routes.map(([route]) => route);
  reports.ready = true;

  reports.renderWorkTable = function (bodyId, rows, emptyText) {
    const body = byId(bodyId);
    if (!body) return;
    if (!rows.length) {
      body.replaceChildren(renderElement('tr', {
        children: [renderElement('td', {className: 'empty', attrs: {colspan: 7}, text: emptyText})],
      }));
      return;
    }
    body.replaceChildren(...rows.map(row => renderElement('tr', {
      className: row.needs_review ? 'row-review' : '',
      children: [
        row.work_date, row.full_task_name, row.description, row.status,
        row.section, row.task_type, row.comment,
      ].map(value => renderElement('td', {text: value || ''})),
    })));
  };

  window.openReportsHub = function () {
    openTask('reports', 'worklogs');
  };
})();
