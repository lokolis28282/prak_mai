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

  sections.home=[['home','ODE']];
  sections.monitoring=[['monitoring','Мониторинг']];
  sections.works=[['worklogs','УВР']];
  sections.warehouse=[
    ['overview','Обзор склада'],['balance','Остатки'],['receipt','Приход'],['issue','Расход'],
    ['inventory','Инвентаризация'],['deliveries','Поставки'],
    ['references','Справочники'],['journal','Все события']
  ];
  sections.reports=[['worklogs','УВР'],['daily','Отчет за смену'],['weekly','Отчет за неделю'],['journal','Складские операции']];
  sections.administration=[
    ['admin_users','Пользователи'],['admin_permissions','Права'],
    ['admin_backups','Резервные копии'],['admin_database','Проверка базы'],
    ['admin_audit','Журнал действий'],['admin_migration','Миграция данных'],
    ['admin_references','Управление справочниками']
  ];

  function formatNumber(value){return Number(value||0).toLocaleString('ru-RU')}
  function openWarehouseProblems(){openTask('warehouse','problems')}
  function openWarehouseEvents(){openTask('warehouse','journal')}

  function renderMonitoringHub(){
    const root=byId('monitoring');
    if(!root)return;
    const label=window.ODE?.monitoring?.manualButtonLabel||'сбор информации по Hostname';
    const title=label.charAt(0).toUpperCase()+label.slice(1);
    root.replaceChildren(renderElement('div',{className:'monitoring-hub',children:[
      renderElement('div',{className:'landing-head compact monitoring-head',children:[
        renderElement('p',{className:'eyebrow',text:'Мониторинг'}),
        renderElement('h2',{text:'Инструменты мониторинга'}),
        renderElement('p',{text:'Сбор сведений о проблемном оборудовании и подготовка сообщения для группы поддержки.'})
      ]}),
      renderElement('button',{className:'monitoring-tool-launcher',attrs:{type:'button','aria-label':title},on:{click:()=>window.openMonitoringManualSearch?.()},children:[
        renderElement('span',{className:'monitoring-tool-icon',attrs:{'aria-hidden':'true'},text:'H'}),
        renderElement('span',{className:'monitoring-tool-copy',children:[
          renderElement('small',{text:'Ручной поиск'}),
          renderElement('strong',{text:title}),
          renderElement('span',{text:'DCIM, статус, модель и адресаты письма'})
        ]}),
        renderElement('span',{className:'monitoring-tool-open',attrs:{'aria-hidden':'true'},text:'Открыть →'})
      ]})
    ]}));
  }

  openMonitoringHub=function(){
    openTask('monitoring','monitoring');
  };

  openWarehouseHub=function(){
    openTask('warehouse','overview');
  };

  function warehouseTypeIcon(type,category){
    const value=String(type||'').toLocaleLowerCase();
    if(category==='Кабели'||category==='Кабельные сборки')return '〰';
    if(/сервер|server/.test(value))return '▣';
    if(/трансив|sfp|qsfp/.test(value))return '⇄';
    if(/коммут|switch|сетев/.test(value))return '⌁';
    if(/диск|ssd|hdd/.test(value))return '◉';
    if(/памят|ram|dimm/.test(value))return '▤';
    if(category==='Комплектующие'||category==='Другое оборудование')return '◇';
    return '◆';
  }

  function warehouseCategoryTotals(rows,category){
    return rows.filter(row=>row.category===category).reduce((result,row)=>({
      positions:result.positions+Number(row.positions||0),
      quantity:result.quantity+Number(row.quantity||0)
    }),{positions:0,quantity:0});
  }

  function warehouseOverviewKpiTile(title,value,onClick,{className='',valueClassName=''}={}){
    return renderButton({className:`warehouse-overview-kpi ${className}`.trim(),onClick,children:[
      renderElement('span',{text:title}),
      renderElement('strong',{className:valueClassName,text:value})
    ]});
  }

  function renderWarehouseOperationalKpis(){
    const stats=state.stats||{};
    const received=Number(stats.received_today||0),issued=Number(stats.issued_today||0);
    const net=received-issued,blockers=Number(stats.data_quality_blockers||0),review=Number(stats.data_quality_review||0);
    return renderElement('div',{className:'warehouse-overview-kpis',children:[
      warehouseOverviewKpiTile('Принято сегодня',formatNumber(received),()=>openTask('warehouse','receipt'),{className:'good'}),
      warehouseOverviewKpiTile('Выдано сегодня',formatNumber(issued),()=>openTask('warehouse','issue'),{className:'warn'}),
      warehouseOverviewKpiTile('Изменение за смену',`${net>=0?'+':''}${formatNumber(net)}`,openWarehouseEvents,{valueClassName:net>=0?'good':'bad'}),
      warehouseOverviewKpiTile('Ошибки учёта',formatNumber(blockers),openWarehouseProblems,{className:blockers>0?'bad':'good'}),
      warehouseOverviewKpiTile('Данные для уточнения',formatNumber(review),openWarehouseProblems,{className:review>0?'warn':''}),
      warehouseOverviewKpiTile('Активные поставки',formatNumber(stats.deliveries),()=>openTask('warehouse','deliveries'))
    ]});
  }

  const warehouseFeedActionTone={RECEIPT_CREATE:'good',RECEIPT_IMPORT:'good',ISSUE_CREATE:'warn',ISSUE_IMPORT:'warn'};

  function renderWarehouseActivityFeed(){
    const events=(state.warehouse_history||[]).filter(row=>!Number(row.is_opening_balance||0)).slice(0,6);
    const list=events.length?events.map(row=>{
      const code=historyActionCode(row);
      return renderElement('div',{className:'warehouse-feed-item',children:[
        renderElement('i',{className:warehouseFeedActionTone[code]||'neutral'}),
        renderElement('span',{text:historyActionLabel(code)}),
        renderElement('small',{text:row.serial_number||row.item_name||row.entity_id||''}),
        renderElement('time',{text:row.event_date||'Дата не указана'})
      ]});
    }):[renderElement('div',{className:'warehouse-feed-empty',text:'Операций пока нет'})];
    return renderElement('div',{className:'panel warehouse-activity-feed',children:[
      renderElement('div',{className:'warehouse-overview-toolbar',children:[
        renderElement('div',{children:[renderElement('h3',{text:'Последние операции'}),renderElement('p',{text:'Обновляется после каждого прихода и расхода.'})]}),
        renderButton({text:'Все события',className:'button',onClick:openWarehouseEvents})
      ]}),
      renderElement('div',{className:'warehouse-feed-list',children:list})
    ]});
  }

  function openWarehouseBalance(category='',type=''){
    openTask('warehouse','balance');
    const categorySelect=byId('uxBalanceCategory'),typeSelect=byId('uxBalanceType'),query=byId('balanceQuery');
    if(query)query.value='';
    if(categorySelect)categorySelect.value=category;
    if(typeSelect)typeSelect.value=[...typeSelect.options].some(option=>option.value===type)?type:'';
    (typeSelect||categorySelect||query)?.dispatchEvent(new Event('input',{bubbles:true}));
  }

  function renderWarehouseOverview(){
    const root=byId('overview');
    if(!root)return;
    const rows=state.warehouse_type_summary||[];
    const categories=[
      'Оборудование','Трансиверы','Память','Накопители',
      'Адаптеры и контроллеры','Комплектующие','Кабели','Кабельные сборки','Другое оборудование'
    ];
    const categoryLabels={
      Оборудование:'Оборудование',Трансиверы:'Трансиверы',Память:'Оперативная память',
      Накопители:'Накопители', 'Адаптеры и контроллеры':'Адаптеры и контроллеры',
      Комплектующие:'Прочие комплектующие',Кабели:'Кабели',
      'Кабельные сборки':'Кабельные сборки','Другое оборудование':'Другое оборудование'
    };
    const categoryClasses={
      Оборудование:'equipment',Трансиверы:'transceivers',Память:'memory',
      Накопители:'drives','Адаптеры и контроллеры':'adapters',
      Комплектующие:'components',Кабели:'cables','Кабельные сборки':'assemblies','Другое оборудование':'other'
    };
    const totalPositions=rows.reduce((sum,row)=>sum+Number(row.positions||0),0);
    const totalQuantity=rows.reduce((sum,row)=>sum+Number(row.quantity||0),0);
    const categoryCards=categories.map(category=>{
      const totals=warehouseCategoryTotals(rows,category);
      return renderButton({className:`warehouse-overview-stat warehouse-overview-stat-${categoryClasses[category]}`,onClick:()=>openWarehouseBalance(category),children:[
        renderElement('span',{text:categoryLabels[category]}),
        renderElement('strong',{text:formatNumber(totals.quantity)}),
        renderElement('small',{text:`${formatNumber(totals.positions)} складских позиций`})
      ]});
    });
    root.replaceChildren(
      renderElement('div',{className:'warehouse-overview-head',children:[
        renderElement('div',{children:[renderElement('p',{className:'eyebrow',text:'Склад'}),renderElement('h2',{text:'Текущий баланс склада'}),renderElement('p',{text:'Нажмите на категорию или тип, чтобы открыть готовую выборку в остатках.'})]}),
        renderButton({text:'Открыть весь баланс',className:'button primary',onClick:()=>openWarehouseBalance()})
      ]}),
      renderElement('div',{className:'warehouse-overview-stats',children:[
        renderElement('div',{className:'warehouse-overview-stat warehouse-overview-stat-total',children:[renderElement('span',{text:'Всего на складе'}),renderElement('strong',{text:formatNumber(totalQuantity)}),renderElement('small',{text:`${formatNumber(totalPositions)} активных позиций`})]}),
        ...categoryCards
      ]}),
      renderWarehouseOperationalKpis(),
      renderWarehouseActivityFeed(),
      renderElement('div',{className:'warehouse-overview-toolbar warehouse-overview-actions',children:[
        renderElement('div',{children:[
          renderButton({text:'Принять',className:'button',onClick:()=>openTask('warehouse','receipt')}),
          renderButton({text:'Выдать',className:'button',onClick:()=>openTask('warehouse','issue')}),
          renderButton({text:'Все типы',className:'button',onClick:()=>openWarehouseBalance()})
        ]})
      ]})
    );
  }

  function installPrimaryNavigation(){
    const navigation=document.querySelector('.section-nav');
    if(!navigation)return;
    navigation.hidden=true;
    navigation.setAttribute('aria-hidden','true');
    const sidebar=document.querySelector('.sidebar');
    if(sidebar){sidebar.hidden=true;sidebar.setAttribute('aria-hidden','true')}
  }

  function configureWarehouseViews(){
    const balance=byId('balance'),movement=byId('equipment');
    const intro=balance?.querySelector(':scope > .import-box');
    if(intro){
      const title=intro.querySelector('strong'),description=intro.querySelector('p');
      if(title)title.textContent='Складские позиции';
      if(description)description.textContent='Поиск по S/N, инвентарному номеру, наименованию, поставщику, категории и размещению.';
    }
    if(movement&&!byId('movementViewHeading')){
      movement.prepend(renderElement('div',{className:'landing-head compact',attrs:{id:'movementViewHeading'},children:[
        renderElement('p',{className:'eyebrow',text:'Склад'}),
        renderElement('h2',{text:'Перемещения'}),
        renderElement('p',{text:'Изменение текущего размещения существующей карточки оборудования.'})
      ]}));
      const importBox=movement.querySelector(':scope > .import-box'),boxes=[...movement.querySelectorAll('.split > .box')];
      if(importBox)importBox.hidden=true;
      if(boxes[0])boxes[0].hidden=true;
      if(boxes[1])boxes[1].querySelector('h3').textContent='Переместить оборудование';
      movement.classList.add('warehouse-movement-view');
    }
    const modalTitle=byId('positionModal')?.querySelector('.modal-head h2');
    if(modalTitle)modalTitle.textContent='Карточка оборудования';
  }

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

  let searchTimer=0,searchSequence=0,searchController=null;
  function closeGlobalSearch(){
    clearTimeout(searchTimer);searchTimer=0;searchSequence+=1;
    if(searchController){searchController.abort();searchController=null}
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
    if(searchController)searchController.abort();
    searchController=new AbortController();
    panel.hidden=false;
    panel.replaceChildren(renderElement('div',{className:'global-search-state',text:'Поиск...'}));
    try{
      const response=await request('/api/global-search?'+new URLSearchParams({query:normalized,limit:'30'}),{signal:searchController.signal});
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
      if(error?.name==='AbortError')return;
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
  const deliverySelection={deliveryId:0,selected:new Set(),loading:false};
  function resetDeliverySelection(deliveryId=deliverySelection.deliveryId){
    deliverySelection.deliveryId=Number(deliveryId)||0;
    deliverySelection.selected.clear();
    syncDeliverySelectionView();
  }
  function syncDeliverySelectionView(){
    document.querySelectorAll('#deliveryLines .delivery-check').forEach(checkbox=>{
      checkbox.checked=deliverySelection.selected.has(Number(checkbox.value));
    });
    const trigger=byId('deliverySelectTrigger');
    if(trigger){
      const count=deliverySelection.selected.size;
      trigger.setAttribute('aria-label',count?`Выбрать все. Выбрано строк: ${count}`:'Выбрать все');
    }
  }
  function closeDeliverySelectionMenu(returnFocus=false){
    const menu=byId('deliverySelectMenu'),trigger=byId('deliverySelectTrigger');
    if(menu)menu.hidden=true;
    if(trigger)trigger.setAttribute('aria-expanded','false');
    if(returnFocus)trigger?.focus();
  }
  function openDeliverySelectionMenu(){
    const menu=byId('deliverySelectMenu'),trigger=byId('deliverySelectTrigger');
    if(!menu||deliverySelection.loading)return;
    menu.hidden=false;trigger?.setAttribute('aria-expanded','true');
    menu.querySelector('[role="menuitem"]')?.focus();
  }
  async function applyDeliverySelection(mode){
    if(!currentDelivery||deliverySelection.loading)return;
    const deliveryId=Number(currentDelivery);
    deliverySelection.loading=true;
    try{
      const response=await request('/api/delivery-selection?'+new URLSearchParams({id:String(deliveryId)}));
      if(deliveryId!==Number(currentDelivery))return;
      const ids=mode==='waiting'?response.waiting_ids:response.all_ids;
      deliverySelection.selected=new Set((ids||[]).map(Number));
      syncDeliverySelectionView();
      if(mode==='waiting'&&!deliverySelection.selected.size){
        notify('В поставке нет позиций в состоянии «Ожидается».');
      }
    }catch(error){
      notify(error.message,true);
    }finally{
      deliverySelection.loading=false;
      closeDeliverySelectionMenu();
    }
  }
  function deliverySelectionMenu(){
    const trigger=renderElement('button',{
      className:'delivery-select-trigger',
      attrs:{id:'deliverySelectTrigger',type:'button','aria-haspopup':'menu','aria-expanded':'false','aria-controls':'deliverySelectMenu'},
      children:[renderElement('span',{text:'Выбрать все'}),renderElement('span',{className:'delivery-select-arrow',attrs:{'aria-hidden':'true'},text:'▾'})],
      on:{click:event=>{
        event.stopPropagation();
        if(byId('deliverySelectMenu')?.hidden)openDeliverySelectionMenu();
        else closeDeliverySelectionMenu();
      },keydown:event=>{
        if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();openDeliverySelectionMenu()}
      }}
    });
    const item=(text,mode)=>renderElement('button',{
      className:'delivery-select-item',attrs:{type:'button',role:'menuitem',tabindex:'-1'},text,
      on:{click:event=>{event.stopPropagation();applyDeliverySelection(mode)}}
    });
    const menu=renderElement('div',{
      className:'delivery-select-menu',attrs:{id:'deliverySelectMenu',role:'menu','aria-label':'Групповой выбор строк',hidden:true},
      children:[item('Выбрать все','all'),item('Выбрать только в состоянии «Ожидается»','waiting')],
      on:{keydown:event=>{
        const items=[...event.currentTarget.querySelectorAll('[role="menuitem"]')],index=items.indexOf(document.activeElement);
        if(event.key==='Escape'){event.preventDefault();closeDeliverySelectionMenu(true)}
        if(event.key==='ArrowDown'){event.preventDefault();items[(index+1+items.length)%items.length]?.focus()}
        if(event.key==='ArrowUp'){event.preventDefault();items[(index-1+items.length)%items.length]?.focus()}
      }}
    });
    return renderElement('div',{className:'delivery-select',children:[trigger,menu]});
  }
  selectedDeliveryLineIds=function(){return [...deliverySelection.selected]};
  window.clearDeliverySelection=()=>resetDeliverySelection(deliverySelection.deliveryId);
  document.addEventListener('click',event=>{
    if(!event.target.closest?.('.delivery-select'))closeDeliverySelectionMenu();
  });
  function deliveryLineRow(line){
    const checkbox=renderInput({type:'checkbox',value:String(line.id)});
    checkbox.className='delivery-check';checkbox.disabled=line.state==='Принято';
    checkbox.checked=deliverySelection.selected.has(Number(line.id));
    checkbox.addEventListener('change',()=>{
      const lineId=Number(line.id);
      if(checkbox.checked)deliverySelection.selected.add(lineId);
      else deliverySelection.selected.delete(lineId);
      syncDeliverySelectionView();
    });
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
      const deliveryId=Number(id);
      if(deliverySelection.deliveryId!==deliveryId)resetDeliverySelection(deliveryId);
      currentDelivery=deliveryId;
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
      table.querySelector('thead th')?.replaceChildren(deliverySelectionMenu());
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
      syncDeliverySelectionView();
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

  // Compatibility names are retained for extensions that used the former
  // flat balance loader. The tree owns paging, filtering and stale responses.
  const BALANCE_CHUNK_SIZE=100;
  let initialBalanceRows=[],balanceSearchTimer=0,balanceSearchSequence=0,balancePageOffset=0,balanceHasMore=false,balanceLoadingMore=false;
  function initServerBalanceSearch(){
    window.warehouseStockTree?.attach();
  }
  function currentBalanceParams(){
    return new URLSearchParams({limit:String(BALANCE_CHUNK_SIZE),offset:String(balancePageOffset)});
  }
  function setBalanceScope(){
    window.warehouseStockTree?.render();
  }
  function installBalanceInfiniteScroll(){}
  async function searchBalanceOnServer(){
    const sequence=++balanceSearchSequence;
    const result=await window.warehouseStockTree?.refresh({clearCache:true});
    if(sequence!==balanceSearchSequence)return;
    return result;
  }

  function inventoryNumberAssignment(card,key){
    const canWrite=['admin','engineer'].includes(state.current_user?.role);
    if(state.migration_full?.read_only||state.migration_pilot?.enabled||!canWrite||!card.serial_number||card.inventory_number)return null;
    const input=renderInput({
      name:'inventory_number',
      placeholder:'Введите полученный инвентарный номер',
      required:true,
      attrs:{maxlength:255,autocomplete:'off','aria-label':'Инвентарный номер'}
    });
    const submit=renderButton({text:'Присвоить номер',primary:true,type:'submit'});
    const form=renderElement('form',{
      className:'equipment-inventory-assignment',
      attrs:{'aria-label':'Присвоить инвентарный номер существующей карточке'},
      children:[
        renderElement('div',{children:[
          renderElement('strong',{text:'Инвентарный номер ещё не получен'}),
          renderElement('p',{text:'Когда номер вернётся из учётного отдела, добавьте его сюда. Карточка останется той же.'})
        ]}),
        renderElement('label',{children:[renderElement('span',{text:'Inventory Number'}),input]}),
        submit
      ]
    });
    form.addEventListener('submit',async event=>{
      event.preventDefault();
      const inventoryNumber=input.value.trim();
      if(!inventoryNumber){input.focus();return}
      submit.disabled=true;
      try{
        const response=await actionJson({
          action:'ASSIGN_INVENTORY_NUMBER',
          serial_number:card.serial_number,
          inventory_number:inventoryNumber
        });
        const assigned=response.position?.inventory_number||inventoryNumber;
        for(const rows of [state.balance,state.searchRows]){
          if(!Array.isArray(rows))continue;
          for(const row of rows){
            if(String(row.serial_number||'').toLocaleUpperCase()===String(card.serial_number).toLocaleUpperCase())row.inventory_number=assigned;
          }
        }
        notify(response.position?.updated===false?'Инвентарный номер уже был присвоен':'Инвентарный номер сохранён');
        await openPositionCard(key);
      }catch(error){
        notify(error.message,true);input.focus();
      }finally{
        submit.disabled=false;
      }
    });
    return form;
  }

  function isMigrationAdministrationContext(position){
    return state.current_user?.role==='admin'
      &&currentSection==='administration'
      &&document.querySelector('.subtab.active')?.dataset.view==='migration_pilot'
      &&Boolean(position.full_reconciliation_id||position.pilot_selection_id);
  }

  function cardTypeCategory(field,value){
    const type=String(value||'').toLocaleLowerCase();
    if(field==='cable_type')return ['aoc','dac'].includes(type)?'Кабельные сборки':'Кабели';
    if(field==='equipment_type')return ['прочее оборудование','other'].includes(type)?'Другое оборудование':'Оборудование';
    if(['трансивер','transceiver'].includes(type))return 'Трансиверы';
    if(['оперативная память','memory','ram'].includes(type))return 'Память';
    if(['ssd','hdd'].includes(type))return 'Накопители';
    if(['сетевой адаптер','nic','hba-адаптер','hba','raid-контроллер','raid controller'].includes(type))return 'Адаптеры и контроллеры';
    if(['аксессуар','accessory','прочий компонент','other'].includes(type))return 'Другое оборудование';
    return 'Комплектующие';
  }

  function positionCardEditor(card,key){
    if(!card.serial_number||!['admin','engineer'].includes(state.current_user?.role))return null;
    const categories=['Оборудование','Трансиверы','Память','Накопители','Адаптеры и контроллеры','Комплектующие','Кабели','Кабельные сборки','Другое оборудование'];
    const currentField=card.cable_type?'cable_type':card.component_type?'component_type':'equipment_type';
    const currentType=card[currentField]||'';
    const currentCategory=card.category||cardTypeCategory(currentField,currentType);
    const category=renderSelect({name:'category',value:currentCategory,options:categories,required:true});
    const type=renderSelect({name:'item_type',required:true});
    const availableTypes=selectedCategory=>{
      const fields=selectedCategory==='Оборудование'?['equipment_type']
        :['Кабели','Кабельные сборки'].includes(selectedCategory)?['cable_type']
        :selectedCategory==='Другое оборудование'?['equipment_type','component_type']
        :['component_type'];
      const values=fields.flatMap(field=>refsOf(field).map(value=>[`${field}:${value}`,value]))
        .filter(([key,value])=>cardTypeCategory(key.split(':')[0],value)===selectedCategory);
      const currentKey=`${currentField}:${currentType}`;
      if(currentType&&!values.some(([value])=>value===currentKey))values.unshift([currentKey,currentType]);
      type.replaceChildren(...values.map(([value,label])=>renderElement('option',{attrs:{value},text:label})));
      if(values.some(([value])=>value===currentKey)&&selectedCategory===currentCategory)type.value=currentKey;
    };
    availableTypes(currentCategory);
    category.addEventListener('change',()=>availableTypes(category.value));
    const referenceSelect=(label,name,kind,value,required=false)=>{
      const values=[...new Set([value,...refsOf(kind)].filter(Boolean))].map(item=>[item,item]);
      if(!required)values.unshift(['','Не указано']);
      return renderElement('label',{children:[renderElement('span',{text:label}),renderSelect({name,value,options:values,required})]});
    };
    const form=renderElement('form',{className:'equipment-card-editor',children:[
      renderElement('div',{className:'equipment-card-editor-head',children:[renderElement('h3',{text:'Редактировать карточку'}),renderElement('p',{text:'S/N и история операций не изменяются.'})]}),
      renderElement('label',{children:[renderElement('span',{text:'Категория'}),category]}),
      renderElement('label',{children:[renderElement('span',{text:'Тип'}),type]}),
      renderElement('label',{children:[renderElement('span',{text:'Наименование'}),renderInput({name:'item_name',value:card.item_name||'',required:true})]}),
      referenceSelect('Поставщик','supplier','supplier',card.supplier||''),
      referenceSelect('Вендор','vendor','vendor',card.vendor||''),
      renderElement('label',{children:[renderElement('span',{text:'Модель'}),renderInput({name:'model',value:card.model||''})]}),
      referenceSelect('Проект','project','project',card.project||''),
      referenceSelect('ЦОД','datacenter','datacenter',card.datacenter||''),
      referenceSelect('Полка','shelf','shelf',card.shelf||''),
      renderElement('label',{children:[renderElement('span',{text:'Объект'}),renderInput({name:'object_name',value:card.object_name||''})]}),
      referenceSelect('Единица','unit','unit',card.unit||''),
      renderButton({text:'Сохранить карточку',className:'button primary',type:'submit'})
    ]});
    form.addEventListener('submit',async event=>{
      event.preventDefault();
      const values=Object.fromEntries(new FormData(form));
      const separator=String(values.item_type||'').indexOf(':');
      const typeField=String(values.item_type||'').slice(0,separator),itemType=String(values.item_type||'').slice(separator+1);
      const fields={item_name:values.item_name,supplier:values.supplier,vendor:values.vendor,model:values.model,project:values.project,shelf:values.shelf,object_name:values.object_name,datacenter:values.datacenter,unit:values.unit,equipment_type:'',component_type:'',cable_type:''};
      if(!['equipment_type','component_type','cable_type'].includes(typeField)){notify('Выберите тип карточки',true);return}
      fields[typeField]=itemType;
      const submit=form.querySelector('button[type="submit"]');submit.disabled=true;
      try{
        const response=await actionJson({action:'UPDATE_POSITION_CARD',serial_number:card.serial_number,fields});
        notify(response.position?.updated===false?'Изменений нет':'Карточка обновлена');
        await loadAll();await openPositionCard(key);
      }catch(error){notify(error.message,true)}finally{submit.disabled=false}
    });
    return form;
  }

  function reviewRowScore(row,position){
    const same=(left,right)=>String(left||'').toLocaleLowerCase()===String(right||'').toLocaleLowerCase();
    let score=0;
    if(same(row.display_serial_value,position.serial_number))score+=20;
    if(same(row.source_serial_value,position.serial_number))score+=10;
    if(same(row.canonical_item_name,position.item_name))score+=8;
    if(same(row.vendor,position.vendor))score+=4;
    if(same(row.model,position.model))score+=4;
    if(row.operation_kind==='receipt')score+=2;
    if(row.has_card)score+=1;
    return score;
  }

  async function positionCardQuery(position){
    if(position.full_reconciliation_id)return new URLSearchParams({full_reconciliation_id:position.full_reconciliation_id});
    if(position.pilot_selection_id)return new URLSearchParams({pilot_selection_id:position.pilot_selection_id});
    const review=state.migration_full?.read_only
      ?{route:'/api/migration-full?',parameter:'full_reconciliation_id'}
      :(state.migration_pilot?.enabled?{route:'/api/migration-pilot?',parameter:'pilot_selection_id'}:null);
    if(review){
      const lookup=position.serial_number||position.item_name||'';
      const response=await request(review.route+new URLSearchParams({query:lookup,limit:'100',offset:'0'}));
      const rows=(response.rows||[]).filter(row=>row.has_card).sort((left,right)=>reviewRowScore(right,position)-reviewRowScore(left,position));
      if(!rows.length)throw new Error('Карточка оборудования не найдена');
      return new URLSearchParams({[review.parameter]:rows[0].selection_id});
    }
    return new URLSearchParams(position.serial_number?{serial_number:position.serial_number}:{
      item_name:position.item_name,cable_type:position.cable_type,project:position.project||'',datacenter:position.datacenter||''
    });
  }

  function userFacingHistoryText(value){
    return String(value??'')
      .replaceAll('MIGRATION_RECEIPT_IMPORTED','Исторический приход')
      .replaceAll('MIGRATION_ISSUE_IMPORTED','Исторический расход')
      .replaceAll('MIGRATION_OPENING_STATE_CREATED','Восстановлена историческая запись')
      .replaceAll('MIGRATION_SOURCE_ROW_LINKED','Связана историческая запись')
      .replaceAll('MIGRATION_EXACT_DUPLICATE_SKIPPED','Повторная историческая запись пропущена')
      .replaceAll('MIGRATION_CONFLICT_RECORDED','Зафиксировано расхождение исторических данных')
      .replaceAll('MIGRATION_NUMERIC_IDENTITY_PROVISIONAL','Историческая карточка требует проверки администратора')
      .replaceAll('MIGRATION_SERIAL_QUARANTINED','Историческая запись изолирована администратором')
      .replaceAll('WAREHOUSE_CARD_RECLASSIFIED','Категория карточки изменена')
      .replaceAll('RECEIPT_FIELDS_FILLED','Данные карточки дополнены')
      .replaceAll('RECEIPT_DATE_FILLED','Дата поступления уточнена')
      .replaceAll('RECEIPT_SERIAL_CORRECTED','S/N карточки исправлен')
      .replace(/Исторический приход\s*\(миграция\)/gi,'Исторический приход')
      .replace(/Исторический расход\s*\(миграция\)/gi,'Исторический расход')
      .replace(/Миграционное начальное состояние/gi,'Восстановленная историческая запись')
      .replace(/Историческая миграция/gi,'Исторические данные')
      .replace(/Миграционн(?:ый|ая|ое|ые)/gi,'Исторический')
      .replace(/Миграци(?:я|и)/gi,'История')
      .replace(/\bMIGRATION_[A-Z_]+\b/g,'Историческое событие');
  }

  function equipmentHistorySummary(title,rows){
    const table=renderTable({
      headers:['Дата','Событие','Количество'],rows:rows.slice(-5),empty:'Записей пока нет',
      rowRenderer:row=>renderElement('tr',{children:[
        renderElement('td',{text:row.date||''}),renderElement('td',{text:row.event_type||''}),renderElement('td',{text:row.quantity})
      ]})
    });
    return renderElement('article',{className:'equipment-history-summary',children:[
      renderElement('h3',{text:title}),renderElement('div',{className:'table-wrap',children:[table]})
    ]});
  }

  function equipmentProductSections(history){
    const workCount=history.filter(row=>/работ|work/i.test(`${row.event_type||''} ${row.task||''}`)).length;
    const productCard=(title,text,future=false)=>renderElement('article',{className:`equipment-product-section${future?' future':''}`,children:[
      renderElement('strong',{text:title}),renderElement('span',{text})
    ]});
    return renderElement('section',{className:'equipment-product-map',attrs:{'aria-label':'Связанные разделы карточки'},children:[
      productCard('Мониторинг','Эта же карточка используется как единая точка оборудования.'),
      productCard('Работы',workCount?`Связанных записей: ${workCount}`:'Связанные работы пока не зарегистрированы.'),
      productCard('Комментарии','Комментарии сохранены в операциях и Timeline.'),
      productCard('Инвентаризация','Сверка выполняется в разделе «Склад → Инвентаризация».'),
      productCard('Фотографии','Запланировано',true),productCard('Документы','Запланировано',true),
      productCard('Гарантия','Запланировано',true),productCard('Комплектующие','Запланировано',true)
    ]});
  }

  openPositionCard=async function(key){
    const position=findPosition(key);
    if(!position)return;
    currentPositionKey=key;
    try{
      const query=await positionCardQuery(position);
      const response=await request('/api/position-card?'+query);
      const card=response.position,migration=response.migration||{},technicalContext=isMigrationAdministrationContext(position);
      const publicText=value=>technicalContext?value:userFacingHistoryText(value);
      const location=[card.datacenter,card.object_name,card.shelf,card.rack_row,card.rack_unit].filter(Boolean).join(' · ');
      const details=[
        ['S/N',card.serial_number],['Инвентарный №',card.inventory_number],
        ['Наименование',card.canonical_name||migration.canonical_item_name||card.item_name],
        ['Вендор',card.vendor||migration.vendor],['Модель',card.model||migration.model],['Part Number',card.part_number||migration.part_number],
        ['Категория',card.category||migration.category],['Тип оборудования',card.item_type||card.equipment_type||migration.equipment_type||migration.component_type],
        ['Текущее местоположение',location],['Hostname',card.hostname],['Проект',card.project],
        ['Статус',card.status],['Поставщик',card.supplier],['Поставка',card.delivery_number],['Заказ',card.order_number],
        ['Дата поступления',card.receipt_date],['Инженер',publicText(card.responsible)],['Комментарий',publicText(card.comment)]
      ];
      if(technicalContext)details.splice(3,0,['Исходное название',card.source_name||migration.source_item_name||card.item_name]);
      const rawHistory=response.history||[];
      currentPositionHistory=(technicalContext?rawHistory:rawHistory.filter(row=>{
        const technicalPayload=`${row.event_type||''} ${row.responsible||''} ${row.comment||''}`;
        return !/MIGRATION_[A-Z_]+|full-warehouse-migration|source_row_hash/i.test(technicalPayload);
      })).map(row=>technicalContext?row:{
        ...row,event_type:userFacingHistoryText(row.event_type),task:userFacingHistoryText(row.task),
        responsible:userFacingHistoryText(row.responsible),comment:userFacingHistoryText(typeof historyDetailText==='function'?historyDetailText(row):row.comment)
      });
      const detailList=renderElement('dl',{className:'equipment-details',children:details.filter(([label,value])=>value||['S/N','Инвентарный №','Статус'].includes(label)).map(([label,value])=>
        renderElement('div',{className:'equipment-field',children:[renderElement('dt',{text:label}),renderElement('dd',{text:value||'—'})]})
      )});
      const detailChildren=[detailList],assignment=inventoryNumberAssignment(card,key),editor=positionCardEditor(card,key);
      if(assignment)detailChildren.push(assignment);
      if(editor)detailChildren.push(editor);
      const receipts=currentPositionHistory.filter(row=>/приход|поступ|восстановлен/i.test(row.event_type||''));
      const issues=currentPositionHistory.filter(row=>/расход|выдан|списан/i.test(row.event_type||''));
      detailChildren.push(renderElement('section',{className:'equipment-history-summaries',children:[
        equipmentHistorySummary('История приходов',receipts),equipmentHistorySummary('История расходов',issues)
      ]}));
      if(response.migration&&technicalContext){
        const sourceRows=Array.isArray(migration.source_rows)?migration.source_rows:[];
        const readable=value=>Array.isArray(value)?value.map(readable).filter(Boolean).join('; '):(value&&typeof value==='object'?Object.entries(value).map(([name,item])=>`${name}: ${readable(item)}`).join('; '):String(value??''));
        const source=[migration.source_file,migration.source_sheet,migration.source_row?`строка ${migration.source_row}`:''].filter(Boolean).join(' · ');
        const pilotMigrationFields=[
          ['Source',source],['Selected Source S/N',migration.source_serial_value],['Preserved Identity S/N',migration.preserved_identity_serial],['Original Item Name',migration.source_item_name],
          ['Canonical Item Name',migration.canonical_item_name],['Preservation Status',migration.serial_preservation_status],
          ['Object Kind',migration.object_kind],['Equipment Category',migration.equipment_category],
          ['Equipment Type',migration.equipment_type],['Component Type',migration.component_type],
          ['Vendor',migration.vendor],['Model',migration.model],['Part Number',migration.part_number],
          ['Supplier',migration.supplier],['Shelf (optional)',migration.shelf],
          ['Source Receipt Date',migration.source_receipt_date],['Source Receipt Date (raw)',migration.source_receipt_date_raw],
          ['Source Date Status',migration.source_date_status],
          ['Migration Warnings',readable(migration.migration_warnings)],['Conflicts',readable(migration.conflicts)]
        ];
        const fullMigrationFields=[
          ['Source',source],['Operation Kind',migration.operation_kind],['Historical Source Date',migration.source_operation_date],
          ['Selected Source S/N',migration.source_serial_value],['Display S/N',migration.display_serial_value],
          ['Preserved Identity S/N',migration.preserved_serial_value],['Raw XML Token',migration.raw_xml_value],
          ['Preservation Status',migration.preservation_status],['Identity Confidence',migration.identity_confidence],
          ['Authoritative',migration.authoritative?'Да':'Нет'],['Requires Manual Review',migration.requires_manual_review?'Да':'Нет'],
          ['Final Status',migration.final_status],['Original Item Name',migration.source_item_name],
          ['Canonical Item Name',migration.canonical_item_name],['Object Kind',migration.object_kind],
          ['Equipment Category',migration.category],['Equipment Type',migration.equipment_type],
          ['Component Type',migration.component_type],['Vendor',migration.vendor],['Model',migration.model],
          ['Part Number',migration.part_number],['Shelf (provenance only)',migration.shelf],
          ['Normalization Rule',migration.normalization_rule],['Opening State',migration.opening_state?'Да':'Нет'],
          ['Opening State Explanation',migration.opening_state_message],
          ['Numeric Preservation Warning',migration.preservation_status==='NUMERIC_FORMAT_UNPROVEN'?'Возможна утрата ведущих нулей; authoritative=false, требуется ручная проверка':''],
          ['Migration Warnings',readable(migration.warnings)],['Conflicts',readable(migration.conflicts)]
        ];
        const migrationFields=migration.mode==='full'?fullMigrationFields:pilotMigrationFields;
        const migrationList=renderElement('dl',{className:'equipment-details migration-details',children:migrationFields.map(([label,value])=>
          renderElement('div',{className:'equipment-field',children:[renderElement('dt',{text:label}),renderElement('dd',{text:value||'—'})]})
        )});
        const fullSource=migration.mode==='full';
        const sourceTable=renderTable({
          headers:fullSource?['Операция','Дата','Файл','Лист','Строка','Source S/N','Display S/N','Финальный статус','Warnings']:['Файл','Лист','Строка','Source S/N','Решение','Warnings'],rows:sourceRows,
          empty:'Связанные source rows отсутствуют',
          rowRenderer:row=>renderElement('tr',{children:fullSource?[
            renderElement('td',{text:row.operation_kind||''}),renderElement('td',{text:row.source_operation_date||''}),
            renderElement('td',{text:row.source_file||''}),renderElement('td',{text:row.source_sheet||''}),
            renderElement('td',{text:row.source_row||''}),renderElement('td',{children:[renderElement('code',{text:row.source_serial_value||''})]}),
            renderElement('td',{children:[renderElement('code',{text:row.display_serial_value||''})]}),
            renderElement('td',{text:row.final_status||''}),renderElement('td',{text:readable(row.migration_warnings)})
          ]:[
            renderElement('td',{text:row.source_file||''}),renderElement('td',{text:row.source_sheet||''}),
            renderElement('td',{text:row.source_row||''}),renderElement('td',{children:[renderElement('code',{text:row.source_serial_value||''})]}),
            renderElement('td',{text:row.import_decision||''}),renderElement('td',{text:readable(row.migration_warnings)})
          ]})
        });
        const relationships=Array.isArray(migration.relationships)?migration.relationships:[];
        const relationshipTable=fullSource&&relationships.length?renderElement('div',{children:[
          renderElement('h4',{text:`Target S/N relationships (${relationships.length})`}),
          renderElement('div',{className:'table-wrap',children:[renderTable({
            headers:['Relationship','Target Source S/N','Target Display S/N','Preservation','Warning'],rows:relationships,
            empty:'Связи отсутствуют',rowRenderer:row=>renderElement('tr',{children:[
              renderElement('td',{text:row.relationship_type||''}),renderElement('td',{children:[renderElement('code',{text:row.target_source_serial_value||''})]}),
              renderElement('td',{children:[renderElement('code',{text:row.target_display_serial_value||''})]}),
              renderElement('td',{text:row.target_preservation_status||''}),renderElement('td',{text:row.warning||''})
            ]})
          })]})
        ]}):null;
        const provenanceChildren=[
          renderElement('h3',{text:'Migration provenance'}),migrationList,
          renderElement('h4',{text:`Source Rows (${sourceRows.length})`}),renderElement('div',{className:'table-wrap',children:[sourceTable]})
        ];
        if(relationshipTable)provenanceChildren.push(relationshipTable);
        detailChildren.push(renderElement('section',{className:'equipment-migration-section',attrs:{'aria-label':'Migration provenance'},children:provenanceChildren}));
      }
      byId('positionDetails').replaceChildren(...detailChildren);
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

  installPrimaryNavigation();
  configureWarehouseViews();

  const baseShowSection=showSection,baseShowView=showView;
  let applyingHistory=false;
  function writeLocation(section,view,replace=false){
    if(applyingHistory)return;
    if(history.state?.section===section&&history.state?.view===view&&!history.state?.card)return;
    const knowledgeRoute=section==='knowledge'?(history.state?.section==='knowledge'&&history.state?.knowledgeRoute||'home'):'';
    const stateValue={section,view,...(knowledgeRoute?{knowledgeRoute}:{})};
    const hash=knowledgeRoute?`#knowledge/${knowledgeRoute.split('/').map(encodeURIComponent).join('/')}`:`#${encodeURIComponent(section)}/${encodeURIComponent(view)}`;
    history[replace?'replaceState':'pushState'](stateValue,'',hash);
  }
  function renderProductRoute(section,view){
    const balanceBody=byId('balanceBody');
    if(section==='warehouse'&&view==='balance')renderSimpleBalance();
    else if(balanceBody?.childElementCount)balanceBody.replaceChildren();
    const referenceBody=byId('referenceBody');
    if(section==='warehouse'&&view==='references')renderReferences();
    else if(referenceBody?.childElementCount)referenceBody.replaceChildren();
    const historyBody=byId('operationBody');
    if((section==='warehouse'||section==='reports')&&view==='journal')renderWarehouseHistory();
    else if(historyBody?.childElementCount)historyBody.replaceChildren();
    if(section==='monitoring'&&view==='monitoring')renderMonitoringHub();
  }
  showSection=function(name){
    applyingHistory=true;baseShowSection(name);applyingHistory=false;
    const view=(sections[name]&&sections[name][0]&&sections[name][0][0])||name;
    renderProductRoute(name,view);
    writeLocation(name,view);window.scrollTo(0,0);
  };
  showView=function(id){baseShowView(id);renderProductRoute(currentSection,id);writeLocation(currentSection,id);window.scrollTo(0,0)};
  openTask=function(section,view){
    applyingHistory=true;baseShowSection(section);baseShowView(view);applyingHistory=false;
    currentSection=section;renderProductRoute(section,view);writeLocation(section,view);window.scrollTo(0,0);
  };
  goHome=function(){openTask('home','home');window.scrollTo(0,0)};
  window.addEventListener('popstate',event=>{
    const target=event.state;if(!target)return;
    if(!target.card&&byId('positionModal')?.classList.contains('show'))closePositionCard();
    applyingHistory=true;baseShowSection(target.section);baseShowView(target.view);applyingHistory=false;
    renderProductRoute(target.section,target.view);
    if(target.section==='knowledge')window.ODE?.knowledge?.renderRoute(target.knowledgeRoute||'home');
  });
  const hashParts=location.hash.replace(/^#/,'').split('/').map(decodeURIComponent);
  const initialSection=sections[hashParts[0]]?hashParts[0]:'home';
  const initialKnowledgeRoute=initialSection==='knowledge'?(window.ODE?.knowledge?.routeFromHash(hashParts.slice(1))||'home'):'';
  const initialView=initialSection==='knowledge'?'knowledge':(sections[initialSection]||[]).some(entry=>entry[0]===hashParts[1])?hashParts[1]:(sections[initialSection]?.[0]?.[0]||'home');
  applyingHistory=true;baseShowSection(initialSection);baseShowView(initialView);applyingHistory=false;
  currentSection=initialSection;
  renderProductRoute(initialSection,initialView);
  history.replaceState({section:initialSection,view:initialView,...(initialKnowledgeRoute?{knowledgeRoute:initialKnowledgeRoute}:{})},'',initialKnowledgeRoute?`#knowledge/${initialKnowledgeRoute.split('/').map(encodeURIComponent).join('/')}`:`#${encodeURIComponent(initialSection)}/${encodeURIComponent(initialView)}`);

  const productLoadAll=loadAll;
  loadAll=async function(){
    await productLoadAll();
    window.clearDeliverySelection?.();
    initialBalanceRows=(state.balance||[]).slice();
    balancePageOffset=0;balanceHasMore=false;balanceLoadingMore=false;
    clearTimeout(balanceSearchTimer);balanceSearchTimer=0;
    initServerBalanceSearch();window.warehouseStockTree?.invalidate();renderWarehouseOverview();
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
