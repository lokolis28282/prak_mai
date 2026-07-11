(function(){
  window.ODE = window.ODE || {};
  window.ODE.coreRouter = {
    sections: () => Object.keys(window.sections || {}),
    goHome,
    showSection,
    showView,
    openTask
  };
})();
