(function(){
  window.ODE = window.ODE || {};
  window.ODE.warehouse = window.ODE.warehouse || {};
  window.ODE.warehouse.balance = {
    render: window.renderSimpleBalance,
    renderKpis: window.renderBalanceKpis,
    setCardFilter: window.setBalanceCardFilter
  };
})();
