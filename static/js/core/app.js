(function(){
  window.ODE = window.ODE || {};
  window.ODE.core = {
    home: {render: window.warehouseLanding, goHome},
    navigation: window.ODE.coreRouter,
    context: window.ODE.context
  };
})();
