(function(){
  window.ODE = window.ODE || {};
  window.ODE.monitoring = {
    enabled: true,
    status: 'Ручной сбор информации по проблемному хосту доступен',
    dependencies: ['Selenium/Microsoft Edge для живого сбора DCIM']
  };

  const manualButtonLabel='сбор информации по Hostname';
  const historyKey='ode_monitoring_manual_search_history';
  const historyLimit=50;

  function preBlock(text){return renderElement('pre',{className:'manual-search-pre',text:text||'—'});}
  function detailRow(label,value){
    return renderElement('div',{className:'equipment-field',children:[
      renderElement('dt',{text:label}),
      renderElement('dd',{text:value||'—'})
    ]});
  }
  async function copyText(text){
    try{
      await navigator.clipboard.writeText(text||'');
      notify('Текст скопирован');
    }catch(error){
      notify('Не удалось скопировать текст автоматически',true);
    }
  }
  function loadManualHistory(){
    try{
      const value=JSON.parse(localStorage.getItem(historyKey)||'[]');
      return Array.isArray(value)?value:[];
    }catch(error){
      return [];
    }
  }
  function saveManualHistory(rows){
    try{
      localStorage.setItem(historyKey,JSON.stringify(rows.slice(0,historyLimit)));
    }catch(error){
      notify('История не сохранена в браузере',true);
    }
  }
  function addManualHistory(event){
    const rows=loadManualHistory();
    const record={id:`${Date.now()}_${Math.random().toString(16).slice(2)}`,event};
    saveManualHistory([record,...rows].slice(0,historyLimit));
  }
  function clearManualHistory(){
    try{localStorage.removeItem(historyKey)}catch(error){}
    renderManualHistory();
    notify('История очищена');
  }
  function eventDetails(event){
    const emailReady=event.email_ready!==false&&Boolean(event.email_text||event.email_body);
    const emailText=event.email_text||event.email_body||'';
    const details=[
      ['Host',event.host],['Тип проблемы',event.problem_type],['Статус',event.task_status],
      ['Ping',event.ping_status],['Модель',event.model],['S/N',event.serial],
      ['ЦОД',event.dc],['Маш.зал',event.room],['Ряд/стойка',event.row],
      ['Тех. владелец',event.owner],['IP',Array.isArray(event.ips)?event.ips.join(', '):''],
      ['Проект',event.email_tag||event.email_project]
    ];
    return renderElement('div',{className:'box manual-search-detail',children:[
      renderElement('h3',{text:'Результат ручного поиска'}),
      renderElement('dl',{className:'equipment-details',children:details.map(([label,value])=>detailRow(label,value))}),
      event.email_routing_warning?renderElement('div',{className:'interface-error',attrs:{role:'alert'},text:event.email_routing_warning}):null,
      renderElement('h3',{text:'Рекомендация'}),
      renderElement('p',{className:'hint',text:event.recommendation||'—'}),
      renderElement('div',{className:'actions',children:[
        renderButton({text:'Скопировать Rooms',className:'button primary',onClick:()=>copyText(event.message)}),
        renderButton({text:'Скопировать письмо',className:'button',disabled:!emailReady,onClick:()=>copyText(emailText)})
      ]}),
      renderElement('h3',{text:'Сообщение Rooms'}),preBlock(event.message),
      renderElement('h3',{text:'Тело письма'}),preBlock(emailText||(emailReady?'—':'Письмо не сформировано: проект hostname не определён.')),
      renderElement('h3',{text:'Лог обработки'}),preBlock((event.logs||[]).join('\n'))
    ]});
  }
  function renderManualResult(result,{persist=true}={}){
    const box=byId('monitoringManualResult');if(!box)return;
    const event=result.event||{};
    if(persist)addManualHistory(event);
    box.replaceChildren(
      result.development_mock?renderElement('div',{className:'interface-error',attrs:{role:'status'},text:'Development mock: запрос к DCIM не выполнялся, результат нельзя считать реальными данными.'}):null,
      eventDetails(event)
    );
    renderManualHistory();
  }
  function renderManualHistory(){
    const root=byId('monitoringManualHistory');if(!root)return;
    const rows=loadManualHistory();
    const head=renderElement('div',{className:'dashboard-section-head',children:[
      renderElement('h3',{text:'История поиска оборудования'}),
      renderButton({text:'Очистить историю',className:'button',disabled:!rows.length,onClick:clearManualHistory})
    ]});
    if(!rows.length){
      root.replaceChildren(renderElement('div',{className:'box',children:[
        head,
        renderElement('p',{className:'hint',text:'История пока пуста. После успешного сбора здесь появятся найденные хостнеймы.'})
      ]}));
      return;
    }
    const table=renderElement('table');
    const tbody=renderElement('tbody');
    table.appendChild(renderElement('thead',{children:[renderElement('tr',{children:[
      renderElement('th',{text:'Хостнейм'}),
      renderElement('th',{text:'Тип проблемы'}),
      renderElement('th',{text:'Статус'}),
      renderElement('th',{text:'Модель'}),
      renderElement('th',{text:'Действия'})
    ]})]}));
    table.appendChild(tbody);
    rows.forEach(record=>{
      const event=record.event||{};
      const button=renderButton({text:'Подробнее',className:'button',onClick:()=>{
        const opened=tbody.querySelector(`tr[data-detail-for="${record.id}"]`);
        if(opened){opened.remove();button.textContent='Подробнее';return;}
        tbody.querySelectorAll('tr[data-detail-for]').forEach(x=>x.remove());
        tbody.querySelectorAll('button[data-history-more]').forEach(x=>x.textContent='Подробнее');
        const detail=renderElement('tr',{attrs:{'data-detail-for':record.id},children:[
          renderElement('td',{attrs:{colspan:'5'},children:[eventDetails(event)]})
        ]});
        row.insertAdjacentElement('afterend',detail);
        button.textContent='Скрыть';
      }});
      button.dataset.historyMore='true';
      const row=renderElement('tr',{children:[
        renderElement('td',{text:event.host||event.input_host||'—'}),
        renderElement('td',{text:event.problem_type||'—'}),
        renderElement('td',{text:event.task_status||'—'}),
        renderElement('td',{text:event.model||'—'}),
        renderElement('td',{children:[button]})
      ]});
      tbody.appendChild(row);
    });
    root.replaceChildren(renderElement('div',{className:'box',children:[
      head,
      renderElement('div',{className:'table-wrap',children:[table]})
    ]}));
  }

  window.openMonitoringManualSearch=function(){
    if(typeof openTask==='function')openTask('monitoring','monitoring');else showSection('monitoring');
    const root=byId('monitoring');if(!root)return;
    root.replaceChildren(
      renderElement('div',{className:'landing-head compact',children:[
        renderElement('p',{className:'eyebrow',text:'Мониторинг'}),
        renderElement('h2',{text:'Ручной поиск'}),
        renderElement('p',{text:'Введите hostname и описание проблемы из Zabbix. Система выполнит стандартную цепочку DCIM -> IP -> ping -> рекомендация -> текст Rooms -> письмо.'})
      ]}),
      renderElement('div',{className:'box',children:[renderElement('form',{className:'form',attrs:{id:'monitoringManualForm'},children:[
        renderElement('label',{text:'Hostname'}),renderInput({name:'host',id:'monitoringManualHost',required:true,placeholder:'msk-dpro-example'}),
        renderElement('label',{text:'Описание проблемы из Zabbix'}),
        renderElement('textarea',{attrs:{name:'problem',id:'monitoringManualProblem',rows:'7',required:'required',placeholder:'BMC: No health data more than 10m'}}),
        renderElement('div',{className:'actions',children:[
          renderButton({text:'Запустить сбор',className:'button primary',type:'submit'}),
          renderButton({text:'Очистить',className:'button',onClick:()=>{byId('monitoringManualForm').reset();byId('monitoringManualResult').replaceChildren();}}),
          renderButton({text:'К мониторингу',className:'button',onClick:()=>openMonitoringHub()})
        ]})
      ]})]}),
      renderElement('div',{attrs:{id:'monitoringManualResult'}}),
      renderElement('div',{attrs:{id:'monitoringManualHistory'}})
    );
    renderManualHistory();
    byId('monitoringManualForm').onsubmit=async event=>{
      event.preventDefault();
      const form=event.currentTarget,submit=event.submitter;if(submit)submit.disabled=true;
      byId('monitoringManualResult').replaceChildren(renderElement('div',{className:'placeholder',text:'Выполняю сбор данных. Если DCIM попросит авторизацию, завершите вход в открывшемся Microsoft Edge.'}));
      try{
        const payload={host:form.elements.host.value,problem:form.elements.problem.value};
        const result=await request('/api/monitoring/manual-search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        renderManualResult(result);
        notify('Ручной поиск завершён');
      }catch(error){
        byId('monitoringManualResult').replaceChildren(renderElement('div',{className:'box error-list',children:[renderElement('h3',{text:'Сбор не завершён'}),renderElement('p',{text:error.message})]}));
        notify(error.message,true);
      }finally{if(submit)submit.disabled=false;}
    };
    byId('monitoringManualHost')?.focus();
  };
  window.ODE.monitoring.manualButtonLabel=manualButtonLabel;
})();
