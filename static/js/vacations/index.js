(function(){
  const V=window.ODE.vacations;
  const renderers={
    vacations_calendar:V.renderCalendar,
    vacations_list:V.renderRequests,
    vacations_employees:V.renderEmployees,
    vacations_conflicts:V.renderConflicts
  };

  V.render=viewId=>{
    const root=byId(viewId);
    if(!root)return;
    const data=V.state.data;
    if(data?.error){
      V.errorView(root,data.error);
      return;
    }
    if(!data){
      V.loadingView(root);
      V.load().catch(()=>{});
      return;
    }
    renderers[viewId]?.(root);
  };
  V.open=()=>{
    showSection('vacations');
    showView('vacations_calendar');
  };
  window.openVacations=V.open;
})();
