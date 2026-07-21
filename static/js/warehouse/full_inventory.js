(function(){
  const STATUS_LABELS={
    NOT_INITIALIZED:'Не инициализирован',
    INVENTORY_IN_PROGRESS:'Инвентаризация выполняется',
    INVENTORY_REVIEW:'Требуется проверка',
    BASELINE_PUBLISHING:'Активация первоначального баланса',
    READY:'Предварительный баланс активен',
    DEGRADED:'Состояние не удалось доказать'
  };
  const SESSION_LABELS={
    DRAFT:'Черновик',UPLOADED:'Файл загружен',PREVIEWING:'Проверка файла',
    REVIEW_REQUIRED:'Есть блокирующие замечания',
    READY_FOR_APPROVAL:'Проверка завершена, требуется согласование',
    FAILED:'Ошибка проверки',REJECTED:'Отменено'
  };
  const MUTATION_IDS=[
    'stockReceiptForm','scanReceiptForm','stockIssueForm','scanIssueForm',
    'bulkIssueForm','addForm','moveForm','deliveryCsv','inventoryNumberCsv'
  ];
  let currentStatus=null;
  let findingsOffset=0;
  let rowsOffset=0;
  const pageSize=100;

  function node(tag,options={}){
    const element=document.createElement(tag);
    if(options.className)element.className=options.className;
    if(options.text!==undefined)element.textContent=String(options.text);
    for(const [name,value] of Object.entries(options.attrs||{})){
      if(value!==null&&value!==undefined)element.setAttribute(name,String(value));
    }
    for(const child of options.children||[])if(child)element.append(child);
    if(options.onClick)element.addEventListener('click',options.onClick);
    return element;
  }

  function button(text,onClick,options={}){
    const result=node('button',{className:`button${options.primary?' primary':''}`,text});
    result.type='button';result.disabled=Boolean(options.disabled);
    if(onClick)result.addEventListener('click',async event=>{
      if(result.disabled)return;
      result.disabled=true;
      try{await onClick(event)}finally{if(result.isConnected)result.disabled=Boolean(options.disabled)}
    });
    return result;
  }

  function statusSession(){return currentStatus?.active_session||null}

  function renderBanner(status){
    const banner=document.getElementById('warehouseSystemBanner');
    if(!banner)return;
    banner.hidden=true;
    banner.replaceChildren();
    banner.className='warehouse-system-banner';
    if(status?.contour?.demo){
      banner.hidden=false;
      banner.classList.add('demo');
      banner.textContent='DEMO — операции выполняются только в disposable базе и не затрагивают рабочий склад.';
      return;
    }
    if(status?.state==='DEGRADED'){
      banner.hidden=false;
      banner.classList.add('degraded');
      banner.textContent='Модуль полной инвентаризации требует проверки. Обычные складские операции сохраняют доступность. '+String(status.degraded_reason||'');
    }
  }

  function applyPostingUi(status){
    const allowed=Boolean(status?.posting_allowed);
    document.body.dataset.warehouseAuthoritative=String(Boolean(status?.authoritative));
    document.body.dataset.warehousePostingAllowed=String(allowed);
    document.body.dataset.warehouseBaselineTimestamp=status?.baseline_timestamp===null?'':String(status?.baseline_timestamp||'');
    for(const id of MUTATION_IDS){
      const root=document.getElementById(id);if(!root)continue;
      const controls=root.matches('input,button,select,textarea')?[root]:[...root.querySelectorAll('input,button,select,textarea')];
      for(const control of controls){
        control.disabled=!allowed;
        control.title=allowed?'':'WAREHOUSE_POSTING_UNAVAILABLE';
      }
    }
  }

  function summaryCard(label,value){
    return node('div',{className:'card',children:[node('span',{text:label}),node('strong',{text:value})]});
  }

  async function refreshStatus(){
    currentStatus=await request('/api/warehouse/system-status');
    if(typeof state!=='undefined')state.warehouse_system=currentStatus;
    renderBanner(currentStatus);applyPostingUi(currentStatus);await renderApp();
  }

  async function createSession(){
    try{
      await request('/api/full-inventory/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      notify('Полная инвентаризация начата');await refreshStatus();
    }catch(error){notify(error.message,true)}
  }

  async function uploadSource(file){
    const session=statusSession();if(!session||!file)return;
    try{
      await request(`/api/full-inventory/upload?session_id=${encodeURIComponent(session.public_id)}`,{
        method:'POST',
        headers:{
          'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'X-Filename':encodeURIComponent(file.name)
        },
        body:file
      });
      notify('XLSX сохранён и проверен');await refreshStatus();
    }catch(error){notify(error.message,true)}
  }

  async function buildPreview(){
    const session=statusSession();if(!session)return;
    try{
      notify('Проверяем XLSX…');
      await request('/api/full-inventory/preview',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({session_id:session.public_id})
      });
      notify('Предварительная проверка завершена');findingsOffset=0;rowsOffset=0;await refreshStatus();
    }catch(error){notify(error.message,true);await refreshStatus()}
  }

  async function recordResolution(item,action){
    let replacement='';
    let target='';
    if(action==='CORRECT_VALUE'){
      replacement=window.prompt(`Новое значение ${item.field_code||''}:`,'')??'';
      if(replacement==='')return;
    }
    if(['CHOOSE_CATALOG_ITEM','CHOOSE_TARGET_LOCATION','LINK_EXISTING_EQUIPMENT'].includes(action)){
      target=window.prompt('Подтверждённое значение:','')??'';
      if(!target.trim())return;
    }
    const reason=window.prompt('Причина решения (обязательно):','Проверено инженером')??'';
    if(!reason.trim())return;
    const session=statusSession();if(!session)return;
    try{
      await request('/api/full-inventory/resolutions',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          session_id:session.public_id,row_id:item.row_id,finding_id:item.finding_id,
          action_code:action,field_code:item.field_code||'',replacement_value:replacement,
          target_public_id:target,reason
        })
      });
      notify('Решение сохранено. Выполните повторную проверку.');await refreshStatus();
    }catch(error){notify(error.message,true)}
  }

  async function revalidate(){
    const session=statusSession();if(!session)return;
    try{
      notify('Повторно проверяем XLSX с решениями…');
      await request('/api/full-inventory/revalidate',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({session_id:session.public_id})
      });
      notify('Повторная проверка завершена');await refreshStatus();
    }catch(error){notify(error.message,true);await refreshStatus()}
  }

  async function buildCandidateRehearsal(){
    const session=statusSession();if(!session)return;
    try{
      notify('Собираем проверочную копию первоначального баланса…');
      const result=await request('/api/full-inventory/candidate-rehearsal',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({session_id:session.public_id})
      });
      notify(`Проверочная копия готова: ${result.snapshot_item_count} позиций`);await refreshStatus();
    }catch(error){notify(error.message,true)}
  }

  async function rejectSession(){
    const session=statusSession();if(!session)return;
    if(!confirm('Отменить текущую инвентаризацию? Загруженный файл и результаты проверки сохранятся для аудита.'))return;
    try{
      await request('/api/full-inventory/reject',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({session_id:session.public_id})
      });
      notify('Инвентаризация отменена');await refreshStatus();
    }catch(error){notify(error.message,true)}
  }

  async function findingsPanel(session){
    const params=new URLSearchParams({session_id:session.public_id,limit:String(pageSize),offset:String(findingsOffset)});
    const filter=document.querySelector('[data-full-inventory-finding-filter]')?.value||'';
    if(filter==='blocking')params.set('blocking','1');
    if(filter==='warning')params.set('severity','WARNING');
    const payload=await request('/api/full-inventory/findings?'+params);
    const table=node('table',{children:[
      node('thead',{children:[node('tr',{children:['Строка','Уровень','Код','Поле','Сообщение','Решение'].map(text=>node('th',{text}))})]}),
      node('tbody',{children:payload.findings.length?payload.findings.map(item=>node('tr',{children:[
        node('td',{text:item.source_row_number||'—'}),node('td',{text:item.blocking?'Блокирующее':item.severity==='WARNING'?'Предупреждение':item.severity}),
        node('td',{text:item.code}),node('td',{text:item.field_code||'—'}),node('td',{text:item.message}),
        item.finding_status==='RESOLVED'?node('td',{text:'Решено'}):node('td',{children:[
          item.field_code?button('Исправить',()=>recordResolution(item,'CORRECT_VALUE')):null,
          button('Исключить',()=>recordResolution(item,'EXCLUDE_ROW'))
        ]})
      ]})):[node('tr',{children:[node('td',{className:'empty',attrs:{colspan:6},text:'Замечаний нет'})]})]})
    ]});
    return node('section',{className:'box full-inventory-evidence',children:[
      node('div',{className:'full-inventory-section-head',children:[
        node('h3',{text:`Замечания (${payload.total})`}),
        node('div',{children:[
          button('Назад',async()=>{findingsOffset=Math.max(0,findingsOffset-pageSize);await renderApp()},{disabled:findingsOffset===0}),
          button('Далее',async()=>{findingsOffset+=pageSize;await renderApp()},{disabled:findingsOffset+pageSize>=payload.total})
        ]})
      ]}),node('div',{className:'table-wrap',children:[table]})
    ]});
  }

  async function rowsPanel(session){
    const params=new URLSearchParams({session_id:session.public_id,limit:String(pageSize),offset:String(rowsOffset)});
    const payload=await request('/api/full-inventory/rows?'+params);
    const table=node('table',{children:[
      node('thead',{children:[node('tr',{children:['Строка','ID строки','Тип','Статус','S/N','Место хранения','Действие'].map(text=>node('th',{text}))})]}),
      node('tbody',{children:payload.rows.length?payload.rows.map(item=>node('tr',{children:[
        node('td',{text:item.source_row_number}),node('td',{text:item.source_row_id}),
        node('td',{text:item.stock_subject_kind}),node('td',{text:item.row_status}),
        node('td',{text:item.raw?.SerialNumber||'—'}),node('td',{text:item.raw?.LocationCode||'—'}),
        node('td',{children:[
          button('Выбрать карточку',()=>recordResolution(item,'CHOOSE_CATALOG_ITEM')),
          item.stock_subject_kind==='SERIALIZED'?button('Создать новую карточку',()=>recordResolution(item,'CREATE_NEW_EQUIPMENT_CANDIDATE')):null
        ]})
      ]})):[node('tr',{children:[node('td',{className:'empty',attrs:{colspan:7},text:'Строки предварительной проверки отсутствуют'})]})]})
    ]});
    return node('section',{className:'box full-inventory-evidence',children:[
      node('div',{className:'full-inventory-section-head',children:[
        node('h3',{text:`Проверенные строки (${payload.total})`}),
        node('div',{children:[
          button('Назад',async()=>{rowsOffset=Math.max(0,rowsOffset-pageSize);await renderApp()},{disabled:rowsOffset===0}),
          button('Далее',async()=>{rowsOffset+=pageSize;await renderApp()},{disabled:rowsOffset+pageSize>=payload.total})
        ]})
      ]}),node('div',{className:'table-wrap',children:[table]})
    ]});
  }

  async function renderApp(){
    const app=document.getElementById('fullInventoryApp');if(!app||!currentStatus)return;
    const inventoryView=app.parentElement;
    for(const child of [...inventoryView.children])if(child!==app)child.hidden=true;
    const session=statusSession();
    const canOperate=state?.current_user?.role==='admin'||state?.current_user?.role==='engineer';
    const header=node('div',{className:'full-inventory-head',children:[
      node('div',{children:[node('p',{className:'eyebrow',text:'Первоначальный учёт'}),node('h2',{text:'Полная инвентаризация склада'}),node('p',{text:'Сначала загрузите заполненный XLSX. Проверка выполняется на отдельной безопасной копии и не меняет рабочую базу.'})]}),
      node('div',{className:'full-inventory-status',children:[node('span',{text:'Состояние'}),node('strong',{text:STATUS_LABELS[currentStatus.state]||currentStatus.state})]})
    ]});
    const actions=node('div',{className:'full-inventory-actions',children:[
      node('a',{className:'button',text:'Скачать XLSX для сканирования',attrs:{href:'/api/full-inventory/template.xlsx'}}),
      !session?button('Начать полную инвентаризацию',createSession,{primary:true,disabled:!canOperate}):null
    ]});
    const children=[header,actions];
    if(!session){
      children.push(node('section',{className:'box full-inventory-guide',children:[
        node('h3',{text:'Как сформировать фактический баланс'}),
        node('ol',{children:[
          node('li',{text:'Скачайте XLSX. В нём уже будут актуальные типы, наименования и полки на отдельных листах.'}),
          node('li',{text:'Загрузите заполненный XLSX и исправьте блокирующие замечания.'}),
          node('li',{text:'Проверьте итоговые количества и передайте результат администратору на согласование.'}),
          node('li',{text:'После контролируемой активации этот список станет новым фактическим балансом.'})
        ]}),
        node('p',{className:'compatibility-notice',text:'До активации операции выполняются относительно текущего предварительного баланса.'})
      ]}));
    }
    if(currentStatus.state==='DEGRADED'){
      children.push(node('div',{className:'full-inventory-error',text:currentStatus.degraded_reason||'Хранилище инвентаризации недоступно'}));
    }
    if(session){
      children.push(node('section',{className:'box',children:[
        node('div',{className:'full-inventory-section-head',children:[
          node('div',{children:[node('h3',{text:SESSION_LABELS[session.session_status]||session.session_status}),node('p',{text:`Номер инвентаризации: ${session.public_id}`})]}),
          button('Отменить инвентаризацию',rejectSession,{disabled:!canOperate||session.session_status==='PREVIEWING'})
        ]}),
        node('div',{className:'cards full-inventory-summary',children:[
          summaryCard('Строк',session.row_count||0),summaryCard('Блокеров',session.blocker_count||0),
          summaryCard('Предупреждений',session.warning_count||0),summaryCard('Информационных',session.informational_count||0)
        ]}),
        node('p',{className:'compatibility-notice',text:'Перед активацией первоначального баланса потребуется подтвердить соответствие мест хранения.'}),
        node('p',{className:'compatibility-notice',text:'Автоматическое сопоставление моделей пока не выполняется. Новые и неоднозначные позиции потребуют ручного решения на следующем этапе.'})
      ]}));
      if(['DRAFT','UPLOADED'].includes(session.session_status)){
        const fileInput=node('input',{attrs:{type:'file',accept:'.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}});
        fileInput.addEventListener('change',async()=>{
          fileInput.disabled=true;
          try{await uploadSource(fileInput.files?.[0])}finally{if(fileInput.isConnected)fileInput.disabled=false}
        });
        const uploadLabel=node('label',{className:'button primary',text:session.session_status==='DRAFT'?'Выбрать XLSX':'Заменить XLSX'});
        uploadLabel.append(fileInput);fileInput.className='file-input';
        const uploadActions=[uploadLabel];
        if(session.session_status==='UPLOADED')uploadActions.push(button('Проверить файл',buildPreview,{primary:true,disabled:!canOperate}));
        children.push(node('div',{className:'full-inventory-upload',children:uploadActions}));
      }
      if(['REVIEW_REQUIRED','READY_FOR_APPROVAL'].includes(session.session_status)){
        const filter=node('select',{attrs:{'data-full-inventory-finding-filter':'true'}});
        for(const [value,label] of [['','Все замечания'],['blocking','Только блокирующие'],['warning','Предупреждения']]){
          const option=node('option',{text:label,attrs:{value}});filter.append(option);
        }
        filter.addEventListener('change',()=>{findingsOffset=0;renderApp()});
        children.push(node('div',{className:'full-inventory-actions',children:[
          filter,button('Повторно проверить',revalidate,{primary:true,disabled:!canOperate})
        ]}));
        try{children.push(await findingsPanel(session));children.push(await rowsPanel(session))}
        catch(error){children.push(node('div',{className:'full-inventory-error',text:error.message}))}
        if(session.session_status==='READY_FOR_APPROVAL'&&state?.current_user?.role==='admin'){
          children.push(node('section',{className:'box',children:[
            node('h3',{text:'Проверочная сборка первоначального баланса'}),
            node('p',{text:'Создаёт и полностью проверяет отдельную копию базы. Рабочая база не заменяется; активация выполняется отдельным контролируемым этапом.'}),
            button('Собрать проверочную копию',buildCandidateRehearsal,{primary:true})
          ]}));
        }
      }
    }
    app.replaceChildren(...children.filter(Boolean));
  }

  const previousLoadAll=loadAll;
  loadAll=async function(){
    await previousLoadAll();
    currentStatus=state.warehouse_system||await request('/api/warehouse/system-status');
    renderBanner(currentStatus);applyPostingUi(currentStatus);await renderApp();
  };

  window.ODE=window.ODE||{};
  window.ODE.fullInventory={refresh:refreshStatus,render:renderApp};
})();
