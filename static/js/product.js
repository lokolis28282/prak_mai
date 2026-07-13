(function(){
  const pendingMutations=new Map();
  const baseRequest=request;
  request=function(url,options={}){
    const method=String(options.method||'GET').toUpperCase();
    if(method==='GET'||method==='HEAD')return baseRequest(url,options);
    const key=[method,url,String(options.body||'')].join('\n');
    if(pendingMutations.has(key))return pendingMutations.get(key);
    const operation=baseRequest(url,options).finally(()=>pendingMutations.delete(key));
    pendingMutations.set(key,operation);
    return operation;
  };

  document.addEventListener('submit',event=>{
    const form=event.target;
    if(!(form instanceof HTMLFormElement))return;
    if(form.dataset.submitting==='true'){
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    form.dataset.submitting='true';
    const submitter=event.submitter;
    if(submitter)submitter.disabled=true;
    window.setTimeout(()=>{
      delete form.dataset.submitting;
      if(submitter)submitter.disabled=false;
    },3000);
  },true);

  sections.warehouse=[
    ['overview','Обзор'],['receipt','Приход'],['issue','Расход'],['balance','Баланс'],
    ['deliveries','Поставки'],['inventory','Инвентаризация'],['problems','Проблемы'],
    ['journal','События']
  ];
  sections.monitoring=[['monitoring','Мониторинг']];

  function formatNumber(value){return Number(value||0).toLocaleString('ru-RU')}
  function openWarehouseProblems(){openTask('warehouse','problems')}
  function openWarehouseEvents(){openTask('warehouse','journal')}

  openMonitoringHub=function(){
    openTask('monitoring','monitoring');
    const root=byId('monitoring');
    if(!root)return;
    root.replaceChildren(renderElement('div',{className:'monitoring-placeholder',children:[
      renderElement('div',{className:'monitoring-icon',text:'M'}),
      renderElement('p',{className:'eyebrow',text:'Мониторинг'}),
      renderElement('h2',{text:'Раздел в разработке'}),
      renderElement('p',{text:'Интеграция с системами мониторинга ЦОД появится после стабильного 1.0.'})
    ]}));
  };

  openWarehouseHub=function(){
    openTask('warehouse','overview');
    const root=byId('overview');
    if(!root)return;
    const actions=[
      ['Принять оборудование','Сканирование, поставка, кабели или ручной ввод',()=>openTask('warehouse','receipt')],
      ['Выдать оборудование','Сканирование, баланс или списание кабелей',()=>openTask('warehouse','issue')],
      ['Поставки','Документы снабжения и приемка',()=>openTask('warehouse','deliveries')],
      ['Баланс','Остатки, поиск и фильтры',()=>openTask('warehouse','balance')],
      ['Инвентаризация','Сверка фактического наличия',()=>openTask('warehouse','inventory')],
      ['Проблемы','Несопоставленные операции и качество данных',openWarehouseProblems],
      ['События','Хронология складских операций',openWarehouseEvents]
    ];
    root.replaceChildren(
      renderElement('div',{className:'landing-head compact',children:[
        renderElement('p',{className:'eyebrow',text:'Склад'}),
        renderElement('h2',{text:'Что нужно сделать?'}),
        renderElement('p',{text:'Выберите рабочий сценарий.'})
      ]}),
      renderElement('div',{className:'action-grid',children:actions.map(([title,help,onClick])=>
        renderButton({className:'warehouse-action',onClick,children:[
          renderElement('strong',{text:title}),renderElement('span',{text:help})
        ]})
      )})
    );
  };

  function dashboardAction(title,help,onClick,primary=false){
    return renderButton({className:`dashboard-action${primary?' primary':''}`,onClick,children:[
      renderElement('strong',{text:title}),renderElement('span',{text:help})
    ]});
  }

  function renderDashboard(){
    const root=byId('home');
    if(!root)return;
    const stats=state.stats||{};
    const recent=(state.warehouse_history||[]).slice(0,8);
    const kpis=[
      ['Оборудование',stats.equipment],['Кабели',stats.cables],
      ['Сегодня принято',stats.received_today],['Сегодня выдано',stats.issued_today],
      ['Проблемы',stats.problems],['Поставки',stats.deliveries]
    ];
    const recentTable=renderTable({
      headers:['Дата','Инженер','Действие','Объект'],rows:recent,empty:'Операций пока нет',
      rowRenderer:row=>renderElement('tr',{children:[
        renderElement('td',{text:row.event_date||''}),
        renderElement('td',{text:row.engineer||'—'}),
        renderElement('td',{text:historyActionLabel(String(row.action||''))}),
        renderElement('td',{text:row.serial_number||row.item_name||row.entity_id||'—'})
      ]})
    });
    root.replaceChildren(
      renderElement('div',{className:'dashboard-head',children:[
        renderElement('div',{children:[renderElement('p',{className:'eyebrow',text:'Главная'}),renderElement('h2',{text:'Смена ODE'})]}),
        renderElement('p',{text:'Состояние склада и быстрые действия на текущий момент.'})
      ]}),
      renderElement('div',{className:'dashboard-kpis',children:kpis.map(([title,value])=>
        renderCard({title,value:formatNumber(value),className:'dashboard-kpi'})
      )}),
      renderElement('h3',{className:'dashboard-section-title',text:'Быстрые действия'}),
      renderElement('div',{className:'dashboard-actions',children:[
        dashboardAction('Принять оборудование','Открыть сценарии прихода',()=>openTask('warehouse','receipt'),true),
        dashboardAction('Выдать оборудование','Открыть сценарии расхода',()=>openTask('warehouse','issue')),
        dashboardAction('Открыть поставку','Найти или загрузить документ',()=>openTask('warehouse','deliveries')),
        dashboardAction('Найти оборудование','Перейти к глобальному поиску',focusGlobalSearch)
      ]}),
      renderElement('div',{className:'dashboard-section-head',children:[
        renderElement('h3',{text:'Последние действия'}),
        renderButton({text:'Все события',className:'button',onClick:openWarehouseEvents})
      ]}),
      renderElement('div',{className:'table-wrap dashboard-recent',children:[recentTable]})
    );
  }

  function resultTitle(result){
    if(result.kind==='position')return result.position.serial_number||result.position.item_name||'Складская позиция';
    if(result.kind==='delivery')return `Поставка ${result.delivery.delivery_number||'#'+result.delivery.id}`;
    return result.engineer.engineer;
  }
  function resultSubtitle(result){
    if(result.kind==='position')return [result.position.item_type,result.position.vendor,result.position.model,result.position.project,result.position.shelf].filter(Boolean).join(' · ');
    if(result.kind==='delivery')return [result.delivery.supplier,result.delivery.status,result.delivery.source_filename].filter(Boolean).join(' · ');
    return `Инженер · последнее действие ${result.engineer.last_activity||''}`;
  }
  function openSearchResult(result){
    closeGlobalSearchModal();
    if(result.kind==='position'){
      state.searchRows=state.searchRows||[];
      if(!state.searchRows.some(row=>row.position_key===result.position.position_key))state.searchRows.push(result.position);
      openPositionCard(encodeURIComponent(result.position.position_key));
    }else if(result.kind==='delivery'){
      openTask('warehouse','deliveries');openDelivery(result.delivery.id);
    }else{
      openWarehouseEvents();
      const input=document.querySelector('#journal .history-search');
      if(input){input.value=result.engineer.engineer;input.dispatchEvent(new Event('input',{bubbles:true}))}
    }
  }

  let searchTimer=0,searchSequence=0;
  function closeGlobalSearch(){
    clearTimeout(searchTimer);searchTimer=0;searchSequence+=1;
    const panel=byId('globalSearchResults'),input=byId('globalSearch');
    if(panel){panel.hidden=true;panel.replaceChildren()}
    if(input)input.setAttribute('aria-expanded','false');
  }
  function closeGlobalSearchModal(){
    const modal=byId('globalSearchModal'),input=byId('globalSearch'),trigger=byId('globalSearchTrigger');
    if(modal)modal.classList.remove('show');
    closeGlobalSearch();
    if(input)input.value='';
    if(trigger)trigger.focus();
  }
  window.closeGlobalSearchModal=closeGlobalSearchModal;
  function openGlobalSearchModal(){
    const modal=byId('globalSearchModal'),input=byId('globalSearch');
    if(!modal||!input)return;
    modal.classList.add('show');
    input.focus();input.select();
  }
  async function runGlobalSearch(query){
    const panel=byId('globalSearchResults');
    if(!panel)return;
    const normalized=query.trim();
    if(normalized.length<2){closeGlobalSearch();return}
    const sequence=++searchSequence;
    panel.hidden=false;
    panel.replaceChildren(renderElement('div',{className:'global-search-state',text:'Поиск...'}));
    try{
      const response=await request('/api/global-search?'+new URLSearchParams({query:normalized,limit:'30'}));
      if(sequence!==searchSequence)return;
      const results=response.results||[];
      panel.replaceChildren(...(results.length?results.map(result=>{
        const button=renderButton({className:'global-search-result',onClick:()=>openSearchResult(result),children:[
          renderElement('strong',{text:resultTitle(result)}),
          renderElement('span',{text:resultSubtitle(result)}),
          renderElement('small',{text:{position:'Оборудование',delivery:'Поставка',engineer:'Инженер'}[result.kind]||'Результат'})
        ]});
        button.setAttribute('role','option');
        return button;
      }):[renderElement('div',{className:'global-search-state',text:'Ничего не найдено'})]));
      byId('globalSearch')?.setAttribute('aria-expanded','true');
    }catch(error){
      if(sequence===searchSequence)panel.replaceChildren(renderElement('div',{className:'global-search-state error-list',text:error.message}));
    }
  }
  function focusGlobalSearch(){openGlobalSearchModal()}
  window.focusGlobalSearch=focusGlobalSearch;

  // Compact header per 0.12.17.1: a magnifying-glass button opens a modal
  // dialog with the search field and results, instead of a permanent input
  // sitting in the header. Debounce, keyboard navigation and reuse of the
  // existing equipment card (openPositionCard) are unchanged from before.
  function initGlobalSearch(){
    const top=document.querySelector('.top');
    if(!top||byId('globalSearch'))return;
    const trigger=renderButton({className:'button search-trigger',onClick:openGlobalSearchModal,children:[
      renderSvgIcon('M11 4a7 7 0 105.06 11.83l4.55 4.56 1.42-1.42-4.56-4.55A7 7 0 0011 4zm0 2a5 5 0 110 10 5 5 0 010-10z')
    ]});
    trigger.id='globalSearchTrigger';
    trigger.setAttribute('aria-label','Поиск по ODE');
    trigger.setAttribute('aria-haspopup','dialog');
    const input=renderInput({id:'globalSearch',placeholder:'S/N, инвентарный №, hostname, поставка, проект...',attrs:{autocomplete:'off','aria-label':'Глобальный поиск'}});
    const panel=renderElement('div',{className:'global-search-results',attrs:{id:'globalSearchResults',hidden:true,role:'listbox'}});
    const closeButton=renderButton({text:'Закрыть',className:'button',onClick:closeGlobalSearchModal});
    const modalCard=renderElement('div',{className:'modal-card global-search-card',children:[
      renderElement('div',{className:'modal-head',children:[renderElement('h2',{text:'Поиск по ODE'}),closeButton]}),
      input,panel
    ]});
    const modal=renderElement('div',{className:'modal global-search-modal',attrs:{id:'globalSearchModal',role:'dialog','aria-modal':'true','aria-label':'Глобальный поиск'},children:[modalCard]});
    top.insertBefore(trigger,top.querySelector('.profile-actions'));
    document.body.appendChild(modal);
    input.addEventListener('input',()=>{
      clearTimeout(searchTimer);searchSequence+=1;
      const query=input.value;if(query.trim().length<2){closeGlobalSearch();return}
      searchTimer=window.setTimeout(()=>runGlobalSearch(query),180);
    });
    input.setAttribute('aria-haspopup','listbox');input.setAttribute('aria-expanded','false');
    input.addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeGlobalSearchModal();return}
      if(event.key==='ArrowDown'){
        const first=panel.querySelector('.global-search-result');
        if(first){event.preventDefault();first.focus()}
      }
    });
    panel.addEventListener('keydown',event=>{
      const items=[...panel.querySelectorAll('.global-search-result')],index=items.indexOf(document.activeElement);
      if(event.key==='ArrowDown'&&index>=0){event.preventDefault();items[Math.min(index+1,items.length-1)].focus()}
      if(event.key==='ArrowUp'&&index>=0){event.preventDefault();if(index===0)input.focus();else items[index-1].focus()}
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeGlobalSearchModal()}
    });
    modal.addEventListener('click',event=>{if(event.target===modal)closeGlobalSearchModal()});
    modal.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();closeGlobalSearchModal()}});
  }

  function textCell(value,editableField='',lineId=0){
    const cell=renderElement('td',{text:value??''});
    if(editableField){
      cell.contentEditable='true';
      cell.addEventListener('blur',()=>saveDeliveryCell(lineId,editableField,cell.innerText));
    }
    return cell;
  }
  function deliveryTypeField(line){
    if(line.component_type)return 'component_type';
    if(line.cable_type)return 'cable_type';
    return 'equipment_type';
  }
  function deliveryLineRow(line){
    const checkbox=renderInput({type:'checkbox',value:String(line.id)});
    checkbox.className='delivery-check';checkbox.disabled=line.state==='Принято';
    return renderElement('tr',{children:[
      renderElement('td',{children:[checkbox]}),textCell(line.serial_number),
      textCell(`${line.state||''}${line.error_text?' · '+line.error_text:''}`),
      textCell(line.item_name,'item_name',line.id),textCell(line.model,'model',line.id),
      textCell(line.vendor,'vendor',line.id),textCell(line.datacenter,'datacenter',line.id),
      textCell(line.shelf,'shelf',line.id),textCell(line.object_name,'object_name',line.id),
      textCell(line.equipment_type||line.component_type||line.cable_type,deliveryTypeField(line),line.id),
      textCell(line.quantity)
    ]});
  }
  openDelivery=async function(id,offset=0){
    try{
      currentDelivery=Number(id);
      const pageSize=500,response=await request('/api/delivery?'+new URLSearchParams({id:String(id),limit:String(pageSize),offset:String(offset)}));
      const delivery=response.delivery,summary=response.summary||{},root=byId('deliveryCard');
      const title=renderElement('div',{children:[
        renderElement('h2',{text:`Поставка ${delivery.delivery_number||'#'+delivery.id}`}),
        renderElement('p',{className:'hint',text:[delivery.supplier,delivery.status].filter(Boolean).join(' · ')})
      ]});
      const exportLink=renderElement('a',{className:'button',attrs:{href:`/export/delivery.csv?id=${Number(id)}`},text:'Скачать результат'});
      const closeButton=renderButton({text:'Закрыть поставку',className:'button',onClick:()=>closeDelivery(Number(id))});
      const header=renderElement('div',{className:'modal-head',children:[title,renderElement('div',{children:[exportLink,' ',closeButton]})]});
      const stats=renderElement('div',{className:'cards delivery-summary',children:[
        ['Всего',summary.total],['Принято',summary.accepted],['Уже на складе',summary.existing],
        ['Ошибки',summary.errors],['Ожидается',summary.waiting]
      ].map(([name,value])=>renderCard({title:name,value:formatNumber(value)}))});

      const scanner=renderInput({id:'deliveryScanner',placeholder:'Сканируйте S/N или QR',attrs:{autocomplete:'off'}});
      scanner.className='delivery-scanner';
      scanner.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();scanDelivery()}});
      const scannerBox=renderElement('div',{className:'box delivery-scanner-box',children:[
        renderElement('h3',{text:'Приемка сканером'}),scanner,
        renderElement('div',{className:'hint',attrs:{id:'deliveryScanResult'}})
      ]});

      const fillField=renderSelect({id:'deliveryFillField',options:[
        ['datacenter','ЦОД'],['shelf','Стеллаж/полка'],['object_name','Объект'],
        ['equipment_type','Тип оборудования'],['component_type','Тип компонента'],
        ['cable_type','Тип кабеля'],['vendor','Вендор'],['model','Модель'],['item_name','Наименование']
      ]});
      const fillValue=renderInput({id:'deliveryFillValue',placeholder:'Значение'});
      const tools=renderElement('div',{className:'import-actions delivery-tools',children:[
        fillField,fillValue,
        renderButton({text:'Заполнить выбранные',className:'button',onClick:()=>fillDelivery(false)}),
        renderButton({text:'Заполнить пустые',className:'button',onClick:()=>fillDelivery(true)}),
        renderButton({text:'Принять выбранные',className:'button primary',onClick:()=>acceptSelectedDelivery()})
      ]});
      const table=renderTable({
        headers:['','S/N','Состояние','Наименование','Модель','Вендор','ЦОД','Полка','Объект','Тип','Кол-во'],
        rows:response.lines||[],empty:'В поставке нет строк',rowRenderer:deliveryLineRow
      });
      table.querySelector('tbody').id='deliveryLines';
      const shownFrom=summary.total?offset+1:0,shownTo=Math.min(offset+(response.lines||[]).length,summary.total||0);
      const pager=renderElement('div',{className:'delivery-pager',children:[
        renderElement('span',{text:`Показаны строки ${shownFrom}–${shownTo} из ${summary.total||0}`}),
        renderButton({text:'Назад',className:'button',disabled:offset<=0,onClick:()=>openDelivery(id,Math.max(0,offset-pageSize))}),
        renderButton({text:'Далее',className:'button',disabled:shownTo>=(summary.total||0),onClick:()=>openDelivery(id,offset+pageSize)})
      ]});
      root.replaceChildren(renderElement('div',{className:'box',children:[
        header,stats,scannerBox,tools,renderElement('div',{className:'table-wrap',children:[table]}),pager
      ]}));
      scanner.focus();
    }catch(error){notify(error.message,true)}
  };

  inventoryCsv=async function(input){
    const file=input.files[0];if(!file)return;
    try{
      const result=await request('/api/import-csv?kind=inventory',{method:'POST',headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(file.name)},body:file});
      inventoryResult=result.rows||[];
      const labels={found:'Найдено',not_found:'Не найдено в базе',missing:'Есть в базе, но не было в скане',duplicates:'Дубли в скане'};
      byId('inventoryCards').replaceChildren(...Object.entries(labels).map(([key,label])=>renderCard({title:label,value:formatNumber(result.stats?.[key])})));
      const visible=inventoryResult.slice(0,1000),body=byId('inventoryBody');
      body.replaceChildren(...visible.map(row=>renderElement('tr',{children:[
        textCell(row.serial_number),textCell(row.status),textCell(row.count||1)
      ]})));
      if(inventoryResult.length>visible.length)body.appendChild(renderElement('tr',{children:[
        renderElement('td',{className:'empty',attrs:{colspan:3},text:`Показаны первые ${visible.length} из ${inventoryResult.length}. Полный результат доступен в экспорте.`})
      ]}));
      byId('inventoryExport').disabled=false;notify('Проверка завершена');
    }catch(error){notify(error.message,true)}finally{input.value=''}
  };

  let initialBalanceRows=[],balanceSearchTimer=0,balanceSearchSequence=0;
  function renderBalanceSearchState(message,busy=false){
    const body=byId('balanceBody');
    if(body){
      body.setAttribute('aria-busy',busy?'true':'false');
      body.replaceChildren(renderElement('tr',{children:[
        renderElement('td',{className:'empty',attrs:{colspan:12},text:message})
      ]}));
    }
    setText('balanceLimit',message);
  }
  function initServerBalanceSearch(){
    const input=byId('balanceQuery');
    if(!input||input.dataset.serverSearch==='true')return;
    input.dataset.serverSearch='true';
    input.oninput=()=>{
      clearTimeout(balanceSearchTimer);balanceSearchTimer=0;
      const sequence=++balanceSearchSequence;
      const query=input.value.trim();
      if(!query){
        state.balance=initialBalanceRows.slice();
        renderSimpleBalance();
        byId('balanceBody')?.setAttribute('aria-busy','false');
        setBalanceScope(Boolean(state.balance_truncated));
        return;
      }
      // Do not leave stale rows actionable while the debounced server search
      // is pending: a user could otherwise open or issue an unrelated item.
      renderBalanceSearchState('Поиск по всей базе...',true);
      setBalanceScope(false,'Поиск по всей базе...');
      balanceSearchTimer=window.setTimeout(()=>{
        balanceSearchTimer=0;searchBalanceOnServer(query,sequence);
      },220);
    };
  }
  function setBalanceScope(truncated,message=''){
    let note=byId('balanceScope');
    if(!note){
      note=renderElement('p',{className:'balance-scope',attrs:{id:'balanceScope'}});
      document.querySelector('#balance .filters')?.insertAdjacentElement('afterend',note);
    }
    note.textContent=message||(truncated?'Показана ограниченная выборка. Используйте поиск, чтобы найти позицию во всей базе.':'Показаны все позиции.');
  }
  async function searchBalanceOnServer(query,sequence=++balanceSearchSequence){
    try{
      const response=await request('/api/balance?'+new URLSearchParams({query,limit:'500'}));
      if(sequence!==balanceSearchSequence||byId('balanceQuery')?.value.trim()!==query)return;
      state.balance=response.rows||[];
      renderSimpleBalance();
      byId('balanceBody')?.setAttribute('aria-busy','false');
      setBalanceScope(Boolean(response.truncated),response.truncated?'Показаны первые 500 совпадений. Уточните запрос.':`Найдено позиций: ${state.balance.length}`);
    }catch(error){
      if(sequence===balanceSearchSequence&&byId('balanceQuery')?.value.trim()===query){
        notify(error.message,true);renderBalanceSearchState('Поиск не выполнен');setBalanceScope(false,'Поиск не выполнен');
      }
    }
  }

  openPositionCard=async function(key){
    const position=findPosition(key);
    if(!position)return;
    currentPositionKey=key;
    const query=new URLSearchParams(position.serial_number?{serial_number:position.serial_number}:{
      item_name:position.item_name,cable_type:position.cable_type,project:position.project||'',datacenter:position.datacenter||''
    });
    try{
      const response=await request('/api/position-card?'+query);
      const card=response.position,details=[
        ['S/N',card.serial_number],['Инвентарный №',card.inventory_number],['Тип',card.item_type],['Категория',card.category],
        ['Вендор',card.vendor],['Модель',card.model],['Hostname',card.hostname],['Название',card.item_name],
        ['Проект',card.project],['ЦОД',card.datacenter],['Полка',card.shelf],['Ряд',card.rack_row],['Юнит',card.rack_unit],
        ['Статус',card.status],['Поставщик',card.supplier],['Поставка',card.delivery_number],['Заказ',card.order_number],
        ['Дата поступления',card.receipt_date],['Инженер',card.responsible],['Комментарий',card.comment]
      ];
      currentPositionHistory=response.history||[];
      byId('positionDetails').replaceChildren(renderElement('dl',{className:'equipment-details',children:details.map(([label,value])=>
        renderElement('div',{className:'equipment-field',children:[renderElement('dt',{text:label}),renderElement('dd',{text:value||'—'})]})
      )}));
      const historyBody=byId('positionHistory');
      historyBody.replaceChildren(...(currentPositionHistory.length?currentPositionHistory.map(row=>renderElement('tr',{children:[
        renderElement('td',{text:row.date||''}),renderElement('td',{text:row.event_type||''}),renderElement('td',{text:row.quantity}),
        renderElement('td',{text:row.task||''}),renderElement('td',{text:row.responsible||''}),renderElement('td',{text:row.comment||''})
      ]})):[renderElement('tr',{children:[renderElement('td',{className:'empty',attrs:{colspan:6},text:'История пока пуста'})]})]));
      const related=(state.problems?.unmatched_issues||[]).filter(row=>(card.serial_number&&row.serial_number===card.serial_number)||(!card.serial_number&&row.item_name===card.item_name));
      byId('positionProblems').replaceChildren(...(related.length?related.map(row=>renderElement('tr',{children:[
        renderElement('td',{text:row.date}),renderElement('td',{text:row.serial_number}),renderElement('td',{text:row.item_name}),
        renderElement('td',{text:row.unmatched_quantity}),renderElement('td',{text:row.comment})
      ]})):[renderElement('tr',{children:[renderElement('td',{className:'empty',attrs:{colspan:5},text:'Связанных проблем нет'})]})]));
      byId('positionModal').classList.add('show');
      byId('positionModal').querySelector('button')?.focus();
      if(!applyingHistory&&history.state?.card!==key){
        history.pushState({...history.state,card:key},'',location.hash);
      }
    }catch(error){notify(error.message,true)}
  };

  const baseShowSection=showSection,baseShowView=showView;
  let applyingHistory=false;
  function writeLocation(section,view,replace=false){
    if(applyingHistory)return;
    if(history.state?.section===section&&history.state?.view===view&&!history.state?.card)return;
    const stateValue={section,view};
    const hash=`#${encodeURIComponent(section)}/${encodeURIComponent(view)}`;
    history[replace?'replaceState':'pushState'](stateValue,'',hash);
  }
  showSection=function(name){
    applyingHistory=true;baseShowSection(name);applyingHistory=false;
    const view=(sections[name]&&sections[name][0]&&sections[name][0][0])||name;
    writeLocation(name,view);
  };
  showView=function(id){baseShowView(id);writeLocation(currentSection,id)};
  openTask=function(section,view){
    applyingHistory=true;baseShowSection(section);baseShowView(view);applyingHistory=false;
    currentSection=section;writeLocation(section,view);
  };
  goHome=function(){openTask('home','home');window.scrollTo(0,0)};
  window.addEventListener('popstate',event=>{
    const target=event.state;if(!target)return;
    if(!target.card&&byId('positionModal')?.classList.contains('show'))closePositionCard();
    applyingHistory=true;baseShowSection(target.section);baseShowView(target.view);applyingHistory=false;
  });
  const hashParts=location.hash.replace(/^#/,'').split('/').map(decodeURIComponent);
  const initialSection=sections[hashParts[0]]?hashParts[0]:'home';
  const initialView=(sections[initialSection]||[]).some(entry=>entry[0]===hashParts[1])?hashParts[1]:(sections[initialSection]?.[0]?.[0]||'home');
  applyingHistory=true;baseShowSection(initialSection);baseShowView(initialView);applyingHistory=false;
  currentSection=initialSection;
  history.replaceState({section:initialSection,view:initialView},'',`#${encodeURIComponent(initialSection)}/${encodeURIComponent(initialView)}`);

  const productLoadAll=loadAll;
  loadAll=async function(){
    await productLoadAll();
    initialBalanceRows=(state.balance||[]).slice();
    initServerBalanceSearch();setBalanceScope(Boolean(state.balance_truncated));
  };
  // 0.12.17.1: ODE always opens the four-module launcher built by
  // warehouseLanding() (static/js/ui.js). renderDashboard() (KPI overview,
  // defined above) is intentionally not called here anymore so it no longer
  // overwrites that screen; kept in case a future "Обзор" tab wants it.
  initGlobalSearch();
  const modal=byId('positionModal'),status=byId('status');
  if(modal){modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');modal.setAttribute('aria-label','Карточка оборудования')}
  if(status){status.setAttribute('role','status');status.setAttribute('aria-live','polite')}
  loadAll().catch(error=>console.error('Product dashboard loading failed',error));
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&byId('positionModal')?.classList.contains('show'))closePositionCard()});
})();
