(function(){
  const domainLabels={
    equipment_category:'Категории',equipment_type:'Типы оборудования',equipment_role:'Роли оборудования',
    component_type:'Типы компонентов',cable_type:'Типы кабелей',vendor:'Вендоры',model:'Модели',
    supplier:'Поставщики',datacenter:'ЦОД',warehouse_location:'Складские локации',
    storage_zone:'Зоны хранения',rack:'Стеллажи',shelf:'Полки',unit_of_measure:'Единицы измерения',
    project:'Проекты',operation_source:'Источники операций',issue_reason:'Причины расхода'
  };
  let editorState=null;

  function activeReferenceTable(){
    const rows=(state.references||[]).filter(row=>row.is_active);
    return renderTable({
      headers:['Справочник','Значение','Связь'],rows,empty:'Активных значений нет',
      rowRenderer:row=>renderElement('tr',{children:[
        renderElement('td',{text:state.reference_kinds?.[row.kind]||row.kind}),
        renderElement('td',{text:row.name}),
        renderElement('td',{text:row.parent_key||'—'})
      ]})
    });
  }

  window.renderReferenceCatalog=function(){
    const root=byId('references');if(!root)return;
    root.dataset.mode='catalog';
    root.replaceChildren(
      renderElement('div',{className:'landing-head compact',children:[
        renderElement('p',{className:'eyebrow',text:'Склад'}),
        renderElement('h2',{text:'Справочники'}),
        renderElement('p',{text:'Формы используют только active canonical значения. Изменения выполняются в «Администрирование ODE».'})
      ]}),
      renderElement('div',{className:'table-wrap',children:[activeReferenceTable()]})
    );
  };

  function valuesForDomain(domain){
    return (editorState?.values||[]).filter(value=>!domain||value.domain_key===domain);
  }

  function impactText(value){
    const usage=value.usage||{};
    return `${Number(usage.operational_rows||0).toLocaleString('ru-RU')} строк · ${Number(usage.cards||0).toLocaleString('ru-RU')} карточек`;
  }

  function aliasText(value){
    const aliases=(editorState?.aliases||[]).filter(alias=>Number(alias.canonical_id)===Number(value.id));
    return aliases.length?aliases.map(alias=>`${alias.source_value} (${alias.resolution_status})`).join(', '):'—';
  }

  async function referenceAction(payload){
    const response=await actionJson(payload);
    await loadReferenceEditor();
    return response;
  }

  async function renameValue(value){
    const display_name=prompt('Новое название',value.display_name);
    if(!display_name||display_name.trim()===value.display_name)return;
    await referenceAction({action:'REFERENCE_RENAME',reference_id:value.id,display_name:display_name.trim()});
    notify('Название обновлено; исторические значения сохранены')
  }

  async function toggleValue(value){
    await referenceAction({action:'TOGGLE_REFERENCE',reference_id:value.id,is_active:!Boolean(value.active)});
    notify(value.active?'Значение отключено':'Значение включено')
  }

  async function mergeValue(value){
    const candidates=valuesForDomain(value.domain_key).filter(item=>item.id!==value.id&&item.scope_key===value.scope_key&&item.active);
    if(!candidates.length){notify('Нет active canonical цели в этом parent scope',true);return}
    const answer=prompt(`ID canonical цели:\n${candidates.slice(0,30).map(item=>`${item.id} — ${item.display_name}`).join('\n')}`,'');
    const target=candidates.find(item=>String(item.id)===String(answer||''));
    if(!target){if(answer)notify('Canonical цель не найдена',true);return}
    const response=await actionJson({action:'REFERENCE_MERGE_PREVIEW',source_id:value.id,target_id:target.id});
    const preview=response.preview;
    const message=[
      `${value.display_name} → ${target.display_name}`,
      `Operational rows: ${preview.usage.operational_rows||0}`,
      `Cards: ${preview.usage.cards||0}`,
      `Aliases: ${(preview.aliases||[]).length}`,
      `Conflict risk: ${preview.conflict_risk}`,
      'Raw operational values не будут переписаны.'
    ].join('\n');
    if(!confirm(message+'\n\nПодтвердить merge?'))return;
    await referenceAction({action:'REFERENCE_MERGE',source_id:value.id,target_id:target.id});
    notify('Merge выполнен с сохранением provenance')
  }

  function renderEditorRows(domain){
    const body=byId('referenceEditorBody');if(!body)return;
    const values=valuesForDomain(domain);
    if(state.current_user?.role==='engineer'){
      body.replaceChildren(...(values.length?values.map(value=>renderElement('tr',{children:[
        renderElement('td',{text:value.display_name}),
        renderElement('td',{text:value.active?'Используется':'Отключено'}),
        renderElement('td',{text:impactText(value)}),
        renderElement('td',{children:[renderButton({text:value.active?'Отключить':'Включить',className:'button',onClick:()=>toggleValue(value).catch(error=>notify(error.message,true))})]})
      ]})):[renderElement('tr',{children:[renderElement('td',{className:'empty',attrs:{colspan:4},text:'Значений нет'})]})]));
      return;
    }
    body.replaceChildren(...(values.length?values.map(value=>renderElement('tr',{children:[
      renderElement('td',{text:value.display_name}),
      renderElement('td',{text:value.active?'Используется':'Отключено'}),
      renderElement('td',{text:value.approval_status}),
      renderElement('td',{text:value.scope_key||'—'}),
      renderElement('td',{text:impactText(value)}),
      renderElement('td',{text:aliasText(value)}),
      renderElement('td',{text:value.created_at||'—'}),
      renderElement('td',{text:value.updated_at||'—'}),
      renderElement('td',{text:value.author||'system'}),
      renderElement('td',{text:value.source||'—'}),
      renderElement('td',{text:Number(value.warning_count||0)?`${value.warning_count} pending`:'—'}),
      renderElement('td',{children:[
        ...(state.current_user?.role==='admin'?[renderButton({text:'Переименовать',className:'button',onClick:()=>renameValue(value).catch(error=>notify(error.message,true))})]:[]),
        renderButton({text:value.active?'Отключить':'Включить',className:'button',onClick:()=>toggleValue(value).catch(error=>notify(error.message,true))}),
        ...(state.current_user?.role==='admin'?[renderButton({text:'Проверить объединение',className:'button',onClick:()=>mergeValue(value).catch(error=>notify(error.message,true))})]:[])
      ]})
    ]})):[renderElement('tr',{children:[renderElement('td',{className:'empty',attrs:{colspan:12},text:'Значений нет'})]})]));
  }

  function renderEditor(){
    const root=byId('references');if(!root)return;
    root.dataset.mode='editor';
    const operator=state.current_user?.role==='engineer';
    const operatorDomains=new Set(['equipment_type','component_type','cable_type','vendor','model','supplier','datacenter','shelf','unit_of_measure','project']);
    const domains=(editorState?.domains||[]).filter(domain=>!operator||operatorDomains.has(domain.domain_key)).map(domain=>[domain.domain_key,domainLabels[domain.domain_key]||domain.display_name]);
    const domain=domains[0]?.[0]||'';
    const parentOptions=(editorState?.values||[]).filter(value=>value.domain_key==='vendor'&&value.active).map(value=>value.display_name);
    const parentList=renderElement('datalist',{attrs:{id:'referenceParentOptions'},children:parentOptions.map(value=>renderElement('option',{attrs:{value}}))});
    const parentInput=renderInput({name:'parent',placeholder:'Выберите производителя модели'});parentInput.setAttribute('list','referenceParentOptions');
    const updateParent=selected=>{const model=selected==='model';parentInput.hidden=!model;parentInput.disabled=!model;if(!model)parentInput.value=''};
    const select=renderSelect({id:'referenceEditorDomain',name:'domain',options:domains,value:domain,onChange:event=>{updateParent(event.target.value);renderEditorRows(event.target.value)}});
    const form=renderElement('form',{className:'filters',attrs:{id:'referenceProposalForm'},children:[
      renderElement('label',{children:[renderElement('span',{text:'Справочник'}),select]}),
      renderInput({name:'value',placeholder:'Новое значение',required:true}),
      parentInput,parentList,
      renderButton({text:'Добавить значение',className:'button primary',type:'submit'})
    ]});
    updateParent(domain);
    form.addEventListener('submit',async event=>{
      event.preventDefault();const data=Object.fromEntries(new FormData(form));
      try{await referenceAction({action:'PROPOSE_REFERENCE',...data});notify('Значение добавлено и ожидает включения')}catch(error){notify(error.message,true)}
    });
    const headers=operator?['Значение','Состояние','Использование','Действие']:['Значение','Состояние','Согласование','Связь','Использование','Псевдонимы','Создано','Изменено','Автор','Источник','Предупреждения','Действия'];
    const table=renderElement('table',{children:[
      renderElement('thead',{children:[renderElement('tr',{children:headers.map(text=>renderElement('th',{text}))})]}),
      renderElement('tbody',{attrs:{id:'referenceEditorBody'}})
    ]});
    root.replaceChildren(
      renderElement('div',{className:'landing-head compact',children:[
        renderElement('p',{className:'eyebrow',text:'Склад'}),
        renderElement('h2',{text:'Управление справочниками'}),
        renderElement('p',{text:operator?'Добавляйте и включайте значения, которые используются в формах прихода и расхода. Отключение не удаляет старые операции.':'Переименование и объединение не переписывают исходные значения в исторических операциях.'})
      ]}),form,renderElement('div',{className:'table-wrap reference-editor-table',children:[table]})
    );
    renderEditorRows(domain);
  }

  async function loadReferenceEditor(){
    editorState=await request('/api/admin?section=references');
    renderEditor();
  }

  window.renderReferenceEditor=function(){
    if(!['admin','engineer'].includes(state.current_user?.role)){notify('Недостаточно прав для управления справочниками',true);goHome();return}
    loadReferenceEditor().catch(error=>notify(error.message,true));
  };
})();
