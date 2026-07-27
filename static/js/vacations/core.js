(function(){
  window.ODE=window.ODE||{};
  const V=window.ODE.vacations=window.ODE.vacations||{};
  V.api='/api/vacations';
  V.monthNames=['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
  V.weekdayNames=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
  V.statusLabels={
    PLANNED:'Запланирован',SUBMITTED:'Отправлен в Сферу',
    APPROVED:'Согласован в Сфере',REJECTED:'Отклонен',CANCELLED:'Отменен'
  };
  V.conflictLabels={
    NONE:'Без конфликтов',PENDING:'Ожидает решения',
    APPROVED_EXCEPTION:'Подтверждено как исключение',REJECTED:'Отклонено'
  };
  V.conflictCodeLabels={
    EMPLOYEE_OVERLAP:'Пересечение отпусков сотрудника',
    LEADERSHIP_OVERLAP:'Пересечение руководителей',
    SUBSTITUTE_OVERLAP:'Подменный уже нужен в другом отпуске',
    DUTY_COVERAGE:'Смена остается без дежурного'
  };
  V.state={data:null,loadingPromise:null,editRequestId:null,visibleMonth:new Date()};
  V.isoLocal=value=>{
    const year=value.getFullYear(),month=String(value.getMonth()+1).padStart(2,'0');
    return `${year}-${month}-${String(value.getDate()).padStart(2,'0')}`;
  };
  V.parseIso=value=>{
    const [year,month,day]=String(value).split('-').map(Number);
    return new Date(year,month-1,day);
  };
  V.periodForMonth=value=>{
    const first=new Date(value.getFullYear(),value.getMonth(),1);
    const start=new Date(first);start.setDate(first.getDate()-(first.getDay()+6)%7);
    const end=new Date(start);end.setDate(start.getDate()+41);
    return {date_from:V.isoLocal(start),date_to:V.isoLocal(end)};
  };
  V.dateText=value=>{
    const parsed=V.parseIso(value);
    return `${parsed.getDate()} ${V.monthNames[parsed.getMonth()]} ${parsed.getFullYear()}`;
  };
  V.periodText=row=>`${V.dateText(row.date_from)} — ${V.dateText(row.date_to)} · ${row.calendar_days} календ. дн.`;
  V.employeeById=id=>(V.state.data?.employees||[]).find(item=>Number(item.id)===Number(id));
  V.optionRows=(items,value='value',label='label')=>items.map(item=>[String(item[value]),String(item[label])]);
  V.badge=(text,kind='')=>renderElement('span',{className:`vacation-badge ${kind}`.trim(),text});
  V.field=(label,control,wide=false)=>renderElement('label',{
    className:`vacation-field${wide?' wide':''}`,
    children:[renderElement('span',{text:label}),control]
  });
  V.pageHead=(title,description,actions=[])=>renderElement('div',{className:'vacation-page-head',children:[
    renderElement('div',{children:[
      renderElement('p',{className:'eyebrow',text:'Отпуска'}),
      renderElement('h2',{text:title}),renderElement('p',{text:description})
    ]}),
    actions.length?renderElement('div',{className:'vacation-head-actions',children:actions}):null
  ]});
  V.loadingView=root=>root.replaceChildren(
    renderElement('div',{className:'vacation-loading',text:'Загрузка календаря отпусков...'})
  );
  V.errorView=(root,message)=>root.replaceChildren(
    renderElement('div',{className:'vacation-empty vacation-error',children:[
      renderElement('h2',{text:'Вкладка отпусков пока недоступна'}),
      renderElement('p',{text:message}),
      renderElement('p',{className:'hint',text:'Отпуска используют отдельную data/vacations.db. Перезапустите приложение, чтобы проверить её инициализацию.'}),
      renderButton({text:'Повторить',className:'button',onClick:()=>V.load(true)})
    ]})
  );
  V.renderActive=()=>{
    const active=document.querySelector('.view.active');
    if(active?.id?.startsWith('vacations_'))V.render(active.id);
  };
  V.load=async(force=false)=>{
    if(V.state.loadingPromise&&!force)return V.state.loadingPromise;
    const period=V.periodForMonth(V.state.visibleMonth);
    V.state.loadingPromise=request(`${V.api}/bootstrap?${new URLSearchParams(period)}`)
      .then(result=>{V.state.data=result;V.renderActive();return result})
      .catch(error=>{V.state.data={error:error.message};V.renderActive();throw error})
      .finally(()=>{V.state.loadingPromise=null});
    return V.state.loadingPromise;
  };
  V.siteLabel=value=>({ixcellerate:'IXcellerate',solar:'Solar',hybrid:'Гибрид'}[value]||'Не задана');
  V.scheduleLabel=value=>value==='ONE_THREE'?'1/3 (24 часа)':value==='FIVE_TWO'?'5/2':'Не задан';
})();
