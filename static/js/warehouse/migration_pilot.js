/* Read-only review UI shared by the pilot and full migration candidates. */
(function(){
  'use strict';

  let initialized=false;
  let activeFilter='';
  let activeOffset=0;
  let lastResponse=null;
  let loadSequence=0;

  const fullMode=()=>Boolean(state.migration_full?.enabled);
  const reviewStatus=()=>fullMode()?state.migration_full:state.migration_pilot;
  const readable=value=>{
    if(Array.isArray(value))return value.map(readable).filter(Boolean).join('; ');
    if(value&&typeof value==='object')return Object.entries(value).map(([key,item])=>`${key}: ${readable(item)}`).join('; ');
    return String(value??'');
  };

  function filterLabel(name){
    return ({
      '':'Все',IMPORT:'IMPORT',QUARANTINE:'QUARANTINE',CONFLICT:'CONFLICT',CORRUPTED:'CORRUPTED',
      TEXT_EXACT:'TEXT_EXACT',NUMERIC_PROVISIONAL:'NUMERIC_PROVISIONAL',SOURCE_CORRUPTED:'SOURCE_CORRUPTED',
      OPENING_STATE:'OPENING_STATE',UNRESOLVED_ISSUE:'UNRESOLVED_ISSUE',EQUIPMENT:'EQUIPMENT',
      COMPONENT:'COMPONENT',VENDOR:'VENDOR',MODEL:'MODEL'
    })[name]||name;
  }

  function filterNames(){
    return fullMode()
      ?['','TEXT_EXACT','NUMERIC_PROVISIONAL','SOURCE_CORRUPTED','CONFLICT','OPENING_STATE','UNRESOLVED_ISSUE','QUARANTINE','EQUIPMENT','COMPONENT','VENDOR','MODEL']
      :['','IMPORT','QUARANTINE','CONFLICT','CORRUPTED'];
  }

  /* Kept as a separate helper so pilot DOM/contract names remain stable. */
  function pilotRoot(){
    let root=byId('migration_pilot');
    if(root)return root;
    const isFull=fullMode();
    root=renderElement('section',{className:'view panel migration-pilot-review',attrs:{id:'migration_pilot'},children:[
      renderElement('div',{className:'landing-head compact',children:[
        renderElement('p',{className:'eyebrow',text:'Администрирование · Миграция данных'}),
        renderElement('h2',{text:isFull?'Проверка полной исторической загрузки':'Проверка исторического прихода'}),
        renderElement('p',{text:isFull
          ?'Все строки прихода и расхода имеют финальный статус. Generated candidate не редактируется вручную.'
          :'Preservation-aware выборка для ручной проверки. Экран не изменяет складские данные.'})
      ]}),
      renderElement('div',{className:'migration-pilot-controls',children:[
        renderElement('form',{attrs:{id:'migrationPilotSearch'},children:[
          renderInput({id:'migrationPilotQuery',name:'query',placeholder:'Точный S/N, наименование, вендор, модель или строка источника',attrs:{autocomplete:'off'}}),
          renderElement('select',{attrs:{id:'migrationFullVendor',title:'Вендор'},children:[renderElement('option',{text:'Все вендоры',attrs:{value:''}})]}),
          renderElement('select',{attrs:{id:'migrationFullModel',title:'Модель'},children:[renderElement('option',{text:'Все модели',attrs:{value:''}})]}),
          renderButton({text:'Найти',primary:true,type:'submit'})
        ]}),
        renderElement('div',{className:'migration-pilot-filters',attrs:{id:'migrationPilotFilters'}})
      ]}),
      renderElement('div',{className:'migration-pilot-counts',attrs:{id:'migrationPilotCounts','aria-live':'polite'}}),
      renderElement('div',{className:'migration-review-page',children:[
        renderElement('p',{className:'hint',attrs:{id:'migrationPilotResultCount'},text:'Загрузка migration review…'}),
        renderElement('div',{children:[
          renderButton({text:'← Назад',className:'button',onClick:()=>changePage(-1)}),
          renderButton({text:'Вперёд →',className:'button',onClick:()=>changePage(1)})
        ]})
      ]}),
      renderElement('div',{className:'table-wrap',children:[
        renderElement('table',{children:[
          renderElement('thead',{children:[renderElement('tr',{children:[
            'Решение','S/N','Preservation','Canonical name','Исходное название','Типизация','Источник','Warnings',''
          ].map(text=>renderElement('th',{text}))})]}),
          renderElement('tbody',{attrs:{id:'migrationPilotBody'},children:[
            renderElement('tr',{children:[renderElement('td',{className:'empty',attrs:{colspan:9},text:'Загрузка…'})]})
          ]})
        ]})
      ]})
    ]});
    const main=document.querySelector('main.main');
    const modal=byId('positionModal');
    if(modal&&modal.parentNode===main)main.insertBefore(root,modal);else main.appendChild(root);
    byId('migrationFullVendor').hidden=!isFull;
    byId('migrationFullModel').hidden=!isFull;
    return root;
  }

  function renderFilters(){
    const root=byId('migrationPilotFilters');
    root.replaceChildren(...filterNames().map(name=>renderButton({
      text:filterLabel(name),
      className:`button migration-pilot-filter${activeFilter===name?' active':''}`,
      dataset:{filter:name||'ALL'},
      onClick:()=>{activeFilter=name;activeOffset=0;renderFilters();loadMigrationPilotRows()}
    })));
  }

  function renderCounts(response){
    const counts=response.counts||{};
    if(fullMode()){
      const cards=[
        ['Source rows',counts.source_rows],['Карточки',counts.imported_cards],['Приходы',counts.imported_receipts],
        ['Расходы',counts.imported_issues],['Numeric provisional',counts.provisional_numeric],['Quarantine',counts.quarantine],
        ['Source corrupted',counts.source_corrupted],['Exact duplicate',counts.exact_duplicates],['Conflicts',counts.conflicts],
        ['Opening states',counts.opening_states],['Unresolved issues',counts.unresolved_issues],['Deferred quantity',counts.deferred_quantity]
      ];
      byId('migrationPilotCounts').replaceChildren(...cards.map(([title,value])=>renderCard({title,value:value||0,className:'card'})));
      return;
    }
    const decisions=response.decisions||{};
    byId('migrationPilotCounts').replaceChildren(
      renderCard({title:'Выбрано',value:response.selected_count||0,className:'card'}),
      renderCard({title:'IMPORT',value:counts.IMPORT||0,className:'card'}),
      renderCard({title:'QUARANTINE',value:counts.QUARANTINE||0,className:'card'}),
      renderCard({title:'CONFLICT',value:counts.CONFLICT||0,className:'card'}),
      renderCard({title:'CORRUPTED',value:counts.CORRUPTED||0,className:'card'}),
      renderCard({title:'Exact duplicate',value:decisions.EXACT_DUPLICATE||0,className:'card'})
    );
  }

  function updateFacets(response){
    if(!fullMode()||!response.facets)return;
    for(const [id,items,label] of [
      ['migrationFullVendor',response.facets.vendors||[],'Все вендоры'],
      ['migrationFullModel',response.facets.models||[],'Все модели']
    ]){
      const select=byId(id),current=select.value;
      if(select.options.length===1)select.replaceChildren(
        renderElement('option',{text:label,attrs:{value:''}}),
        ...items.map(value=>renderElement('option',{text:value,attrs:{value}}))
      );
      select.value=current;
    }
  }

  function sourceText(row){
    return [row.source_file,row.source_sheet,row.source_row?`строка ${row.source_row}`:''].filter(Boolean).join(' · ');
  }

  function typingText(row){
    return [row.object_kind,row.category||row.equipment_category,row.equipment_type||row.component_type,row.vendor,row.model,row.part_number].filter(Boolean).join(' · ');
  }

  function serialCell(row){
    const display=row.display_serial_value||row.source_serial_value||'—';
    const children=[renderElement('code',{className:'pilot-serial',text:display})];
    if(row.serial_preservation_status==='NUMERIC_FORMAT_UNPROVEN'&&row.raw_xml_value){
      children.push(renderElement('small',{className:'migration-raw-token',text:`raw: ${row.raw_xml_value}`}));
      children.push(renderElement('small',{className:'migration-numeric-warning',text:'Возможна утрата ведущих нулей'}));
    }
    return renderElement('div',{children});
  }

  function pilotCardButton(row){
    if(!row.has_card)return renderElement('span',{className:'hint',text:'Карточка не создана'});
    const dataset=fullMode()?{fullReconciliationId:row.selection_id}:{pilotSelectionId:row.selection_id};
    return renderButton({
      text:'Открыть карточку',primary:true,
      dataset,
      onClick:()=>openMigrationPilotCard(row)
    });
  }

  function renderRows(response){
    const body=byId('migrationPilotBody');
    const rows=response.rows||[];
    const start=rows.length?Number(response.offset||0)+1:0;
    const end=Number(response.offset||0)+rows.length;
    const resultCount=byId('migrationPilotResultCount');
    resultCount.textContent=`Показано ${start}–${end} из ${response.total||0}`;
    resultCount.dataset.loadedFilter=activeFilter||'ALL';
    body.replaceChildren(...(rows.length?rows.map(row=>renderElement('tr',{dataset:{decision:row.import_decision||'',filterBucket:row.filter_bucket||''},children:[
      renderElement('td',{children:[renderBadge(row.import_decision||'UNKNOWN',`badge pilot-decision decision-${String(row.import_decision||'unknown').toLocaleLowerCase()}`),renderElement('small',{text:row.operation_kind||''})]}),
      renderElement('td',{children:[serialCell(row)]}),
      renderElement('td',{text:row.serial_preservation_status||'—'}),
      renderElement('td',{text:row.canonical_item_name||'—'}),
      renderElement('td',{text:row.source_item_name||'—'}),
      renderElement('td',{text:typingText(row)||'—'}),
      renderElement('td',{text:sourceText(row)||'—'}),
      renderElement('td',{text:readable([row.migration_warnings,row.conflicts,row.non_application_reason])||'—'}),
      renderElement('td',{children:[pilotCardButton(row)]})
    ]})):[renderElement('tr',{children:[renderElement('td',{className:'empty',attrs:{colspan:9},text:'Для фильтра строк нет'})]})]));
  }

  function changePage(direction){
    if(!lastResponse)return;
    const limit=Number(lastResponse.limit||300);
    const next=Math.max(0,activeOffset+direction*limit);
    if(direction>0&&next>=Number(lastResponse.total||0))return;
    activeOffset=next;loadMigrationPilotRows();
  }

  async function loadMigrationPilotRows(){
    const sequence=++loadSequence;
    try{
      const params=new URLSearchParams({limit:'300',offset:String(activeOffset)});
      if(activeFilter)params.set('filter',activeFilter);
      const query=byId('migrationPilotQuery')?.value||'';
      if(query)params.set('query',query);
      if(fullMode()){
        const vendor=byId('migrationFullVendor')?.value||'',model=byId('migrationFullModel')?.value||'';
        if(vendor)params.set('vendor',vendor);if(model)params.set('model',model);
      }
      const route=fullMode()?'/api/migration-full?':'/api/migration-pilot?';
      const response=await request(route+params);
      if(sequence!==loadSequence)return;
      lastResponse=response;renderCounts(response);updateFacets(response);renderRows(response);
    }catch(error){
      if(sequence!==loadSequence)return;
      byId('migrationPilotResultCount').textContent='Migration review не загружен';
      notify(error.message,true);
    }
  }

  function openMigrationPilotCard(row){
    const isFull=fullMode();
    const positionKey=isFull?`migration-full:${row.selection_id}`:`migration-pilot:${row.selection_id}`;
    const position={
      position_key:positionKey,
      serial_number:row.display_serial_value||row.source_serial_value,
      item_name:row.canonical_item_name,vendor:row.vendor,model:row.model,shelf:row.shelf
    };
    if(isFull)position.full_reconciliation_id=row.selection_id;
    else position.pilot_selection_id=row.selection_id;
    state.searchRows=(state.searchRows||[]).filter(item=>item.position_key!==positionKey);
    state.searchRows.push(position);
    openPositionCard(encodeURIComponent(positionKey));
  }
  window.openMigrationPilotCard=openMigrationPilotCard;

  function markCandidateService(){
    if(!reviewStatus()?.read_only&&!reviewStatus()?.review_read_only)return;
    document.body.classList.add('migration-pilot-active');
    if(fullMode())document.body.classList.add('migration-full-active');
  }

  function configureMigrationPilot(){
    if(!reviewStatus()?.enabled)return;
    markCandidateService();
    if(state.current_user?.role!=='admin')return;
    const database=byId('migrationPilotDatabase');
    if(database)database.textContent=`DB: ${reviewStatus().database}`;
    pilotRoot();
    if(!sections.administration.some(entry=>entry[0]==='migration_pilot')){
      sections.administration.push(['migration_pilot','Миграция данных']);
    }
    if(!initialized){
      initialized=true;renderFilters();
      byId('migrationPilotSearch').addEventListener('submit',event=>{
        event.preventDefault();activeOffset=0;loadMigrationPilotRows();
      });
      byId('migrationFullVendor')?.addEventListener('change',()=>{activeOffset=0;loadMigrationPilotRows()});
      byId('migrationFullModel')?.addEventListener('change',()=>{activeOffset=0;loadMigrationPilotRows()});
    }
  }

  const baseShowView=showView;
  showView=function(id){
    baseShowView(id);
    if(id==='migration_pilot'&&state.current_user?.role==='admin'){
      configureMigrationPilot();loadMigrationPilotRows();
    }
  };
  const baseLoadAll=loadAll;
  loadAll=async function(){await baseLoadAll();configureMigrationPilot()};
})();
