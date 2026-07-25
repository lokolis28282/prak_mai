(function(){
  window.ODE = window.ODE || {};
  window.ODE.context = {
    featureFlags: {
      FEATURE_WAREHOUSE: true,
      FEATURE_REPORTS: true,
      FEATURE_MONITORING: false,
      FEATURE_MOBILE: false,
      FEATURE_EXTERNAL_API: false
    },
    currentUser: () => window.state?.current_user || {}
  };
})();
