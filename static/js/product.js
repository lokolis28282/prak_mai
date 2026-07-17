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
  sections.works=[['worklogs','Журнал работ']];
  sections.warehouse=[
    ['overview','Обзор склада'],['balance','Оборудование'],['receipt','Приход'],['issue','Расход'],
    ['inventory','Инвентаризация'],['deliveries','Поставки'],['equipment','Перемещения'],
    ['references','Справочники']
  ];
  sections.reports=[['daily','Ежедневный'],['weekly','Еженедельный'],['journal','Складские операции']];
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
    if(category==='Кабели')return '〰';
    if(/сервер|server/.test(value))return '▣';
    if(/трансив|sfp|qsfp/.test(value))return '⇄';
    if(/коммут|switch|сетев/.test(value))return '⌁';
    if(/диск|ssd|hdd/.test(value))return '◉';
    if(/памят|ram|dimm/.test(value))return '▤';
    return category==='Компоненты'?'◇':'◆';
  }

  function warehouseCategoryTotals(rows,category){
    return rows.filter(row=>row.category===category).reduce((result,row)=>({
      positions:result.positions+Number(row.positions||0),
      quantity:result.quantity+Number(row.quantity||0)
    }),{positions:0,quantity:0});
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
    const categories=['Оборудование','Компоненты','Кабели'];
    const categoryLabels={Оборудование:'Оборудование',Компоненты:'Компоненты',Кабели:'Кабели и расходники'};
    const totalPositions=rows.reduce((sum,row)=>sum+Number(row.positions||0),0);
    const categoryCards=categories.map(category=>{
      const totals=warehouseCategoryTotals(rows,category);
      return renderButton({className:`warehouse-overview-stat warehouse-overview-stat-${category==='Оборудование'?'equipment':category==='Компоненты'?'components':'cables'}`,onClick:()=>openWarehouseBalance(category),children:[
        renderElement('span',{text:categoryLabels[category]}),
        renderElement('strong',{text:formatNumber(totals.positions)}),
        renderElement('small',{text:'позиций в наличии'})
      ]});
    });
    const typeGroups=categories.map(category=>{
      const items=rows.filter(row=>row.category===category);
      if(!items.length)return null;
      return renderElement('section',{className:'warehouse-type-group',children:[
        renderElement('div',{className:'warehouse-type-heading',children:[
          renderElement('h3',{text:categoryLabels[category]}),
          renderButton({text:'Показать все',className:'warehouse-link-button',onClick:()=>openWarehouseBalance(category)})
        ]}),
        renderElement('div',{className:'warehouse-type-grid',children:items.map(row=>renderButton({
          className:'warehouse-type-card',onClick:()=>openWarehouseBalance(category,row.item_type),children:[
            renderElement('span',{className:'warehouse-type-icon',text:warehouseTypeIcon(row.item_type,category)}),
            renderElement('span',{className:'warehouse-type-name',text:balanceTypeLabel(row.item_type)}),
            renderElement('strong',{text:formatNumber(row.positions)}),
            renderElement('small',{text:`Остаток: ${formatNumber(row.quantity)}`})
          ]
        }))})
      ]});
    }).filter(Boolean);
    root.replaceChildren(
      renderElement('div',{className:'warehouse-overview-head',children:[
        renderElement('div',{children:[renderElement('p',{className:'eyebrow',text:'Склад'}),renderElement('h2',{text:'Всё оборудование — одним взглядом'}),renderElement('p',{text:'Нажмите на категорию или тип, чтобы открыть готовую выборку в балансе.'})]}),
        renderButton({text:'Открыть весь баланс',className:'button primary',onClick:()=>openWarehouseBalance()})
      ]}),
      renderElement('div',{className:'warehouse-overview-stats',children:[
        renderElement('div',{className:'warehouse-overview-stat warehouse-overview-stat-total',children:[renderElement('span',{text:'Всего на складе'}),renderElement('strong',{text:formatNumber(totalPositions)}),renderElement('small',{text:'активных позиций'})]}),
        ...categoryCards
      ]}),
      renderElement('div',{className:'warehouse-overview-toolbar',children:[
        renderElement('div',{children:[renderElement('h3',{text:'По типам'}),renderElement('p',{text:'Серверы, трансиверы, диски и остальные типы из справочника.'})]}),
        renderElement('div',{children:[
          renderButton({text:'Принять',className:'button',onClick:()=>openTask('warehouse','receipt')}),
          renderButton({text:'Выдать',className:'button',onClick:()=>openTask('warehouse','issue')})
        ]})
      ]}),
      ...typeGroups
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
      if(title)title.textContent='Карточки оборудования';
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

  let initialBalanceRows=[],balanceSearchTimer=0,balanceSearchSequence=0,balancePageOffset=0,balanceHasMore=false;
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
    const controls=[input,byId('uxBalanceCategory'),byId('uxBalanceType'),byId('uxBalanceProject'),byId('uxBalanceSupplier'),byId('uxBalanceVendor'),byId('uxBalanceStock'),byId('uxBalanceSort')].filter(Boolean);
    const refresh=event=>{
      clearTimeout(balanceSearchTimer);balanceSearchTimer=0;
      const sequence=++balanceSearchSequence;
      balancePageOffset=0;
      const params=currentBalanceParams();
      const hasFilters=[...params.entries()].some(([key,value])=>!['limit','offset'].includes(key)&&value&&!(key==='sort_by'&&value==='item_name')&&!(key==='sort_dir'&&value==='asc'));
      if(!hasFilters){
        state.balance=initialBalanceRows.slice();
        balanceHasMore=Boolean(state.balance_truncated);
        renderSimpleBalance();
        byId('balanceBody')?.setAttribute('aria-busy','false');
        setBalanceScope(Boolean(state.balance_truncated));
        return;
      }
      if(!state.balance_truncated&&!params.get('query')){
        state.balance=initialBalanceRows.slice();renderSimpleBalance();setBalanceScope(false);return;
      }
      renderBalanceSearchState('Поиск по всей базе...',true);
      setBalanceScope(false,'Поиск по всей базе...');
      balanceSearchTimer=window.setTimeout(()=>{
        balanceSearchTimer=0;searchBalanceOnServer(params,sequence);
      },event?.target===input?220:0);
    };
    controls.forEach(control=>{control.oninput=refresh;control.onchange=refresh});
  }
  function currentBalanceParams(){
    const sort=(byId('uxBalanceSort')?.value||'item_name:asc').split(':');
    return new URLSearchParams({
      query:byId('balanceQuery')?.value.trim()||'',category:byId('uxBalanceCategory')?.value||'',
      item_type:byId('uxBalanceType')?.value||'',project:byId('uxBalanceProject')?.value||'',
      supplier:byId('uxBalanceSupplier')?.value||'',vendor:byId('uxBalanceVendor')?.value||'',
      stock_state:byId('uxBalanceStock')?.value||'',sort_by:sort[0]||'item_name',
      sort_dir:sort[1]||'asc',limit:'500',offset:String(balancePageOffset)
    });
  }
  function setBalanceScope(truncated,message=''){
    let note=byId('balanceScope');
    if(!note){
      note=renderElement('p',{className:'balance-scope',attrs:{id:'balanceScope'}});
      document.querySelector('#balance .filters')?.insertAdjacentElement('afterend',note);
    }
    note.textContent=message||(truncated?'Показана ограниченная выборка. Используйте поиск, чтобы найти позицию во всей базе.':'Показаны все позиции.');
    renderBalancePager();
  }
  function renderBalancePager(){
    let pager=byId('balancePager');
    if(!pager){pager=renderElement('div',{className:'balance-pager',attrs:{id:'balancePager'}});byId('balanceScope')?.insertAdjacentElement('afterend',pager)}
    const page=Math.floor(balancePageOffset/500)+1;
    pager.replaceChildren(
      renderButton({text:'← Предыдущая',className:'button',disabled:balancePageOffset===0,onClick:()=>changeBalancePage(-1)}),
      renderElement('span',{text:`Страница ${page} · строки ${balancePageOffset+1}–${balancePageOffset+state.balance.length}`}),
      renderButton({text:'Следующая →',className:'button',disabled:!balanceHasMore,onClick:()=>changeBalancePage(1)})
    );
  }
  function changeBalancePage(direction){
    balancePageOffset=Math.max(0,balancePageOffset+direction*500);
    const sequence=++balanceSearchSequence;
    renderBalanceSearchState('Загружаем страницу...',true);
    searchBalanceOnServer(currentBalanceParams(),sequence);
  }
  async function searchBalanceOnServer(params,sequence=++balanceSearchSequence){
    try{
      const expected=params.toString();
      const response=await request('/api/balance?'+expected);
      if(sequence!==balanceSearchSequence||currentBalanceParams().toString()!==expected)return;
      state.balance=response.rows||[];
      balancePageOffset=Number(response.offset||0);
      balanceHasMore=Boolean(response.has_more);
      renderSimpleBalance();
      byId('balanceBody')?.setAttribute('aria-busy','false');
      setBalanceScope(Boolean(response.has_more),response.has_more?'Есть следующая страница результатов.':`Показано позиций на странице: ${state.balance.length}`);
    }catch(error){
      if(sequence===balanceSearchSequence){
        notify(error.message,true);renderBalanceSearchState('Поиск не выполнен');setBalanceScope(false,'Поиск не выполнен');
      }
    }
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
        ['Каноническое название',card.canonical_name||migration.canonical_item_name||card.item_name],['Исходное название',card.source_name||migration.source_item_name||card.item_name],
        ['Вендор',card.vendor||migration.vendor],['Модель',card.model||migration.model],['Part Number',card.part_number||migration.part_number],
        ['Категория',card.category||migration.category],['Тип оборудования',card.item_type||card.equipment_type||migration.equipment_type||migration.component_type],
        ['Текущее местоположение',location],['Hostname',card.hostname],['Проект',card.project],['ЦОД',card.datacenter],
        ['Полка',card.shelf],['Ряд',card.rack_row],['Юнит',card.rack_unit],
        ['Статус',card.status],['Поставщик',card.supplier],['Поставка',card.delivery_number],['Заказ',card.order_number],
        ['Дата поступления',card.receipt_date],['Инженер',publicText(card.responsible)],['Комментарий',publicText(card.comment)]
      ];
      const rawHistory=response.history||[];
      currentPositionHistory=(technicalContext?rawHistory:rawHistory.filter(row=>{
        const technicalPayload=`${row.event_type||''} ${row.responsible||''} ${row.comment||''}`;
        return !/MIGRATION_[A-Z_]+|full-warehouse-migration|source_row_hash/i.test(technicalPayload);
      })).map(row=>technicalContext?row:{
        ...row,event_type:userFacingHistoryText(row.event_type),task:userFacingHistoryText(row.task),
        responsible:userFacingHistoryText(row.responsible),comment:userFacingHistoryText(row.comment)
      });
      const detailList=renderElement('dl',{className:'equipment-details',children:details.map(([label,value])=>
        renderElement('div',{className:'equipment-field',children:[renderElement('dt',{text:label}),renderElement('dd',{text:value||'—'})]})
      )});
      const detailChildren=[detailList],assignment=inventoryNumberAssignment(card,key);
      if(assignment)detailChildren.push(assignment);
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
    if(section==='monitoring'&&view==='monitoring')renderMonitoringHub();
  }
  showSection=function(name){
    applyingHistory=true;baseShowSection(name);applyingHistory=false;
    const view=(sections[name]&&sections[name][0]&&sections[name][0][0])||name;
    renderProductRoute(name,view);
    writeLocation(name,view);
  };
  showView=function(id){baseShowView(id);renderProductRoute(currentSection,id);writeLocation(currentSection,id)};
  openTask=function(section,view){
    applyingHistory=true;baseShowSection(section);baseShowView(view);applyingHistory=false;
    currentSection=section;renderProductRoute(section,view);writeLocation(section,view);
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
    initialBalanceRows=(state.balance||[]).slice();
    balancePageOffset=0;balanceHasMore=Boolean(state.balance_truncated);
    initServerBalanceSearch();setBalanceScope(Boolean(state.balance_truncated));renderWarehouseOverview();
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
