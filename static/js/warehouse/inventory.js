(function(){
  window.ODE=window.ODE||{};
  window.ODE.warehouse=window.ODE.warehouse||{};

  const KIND='inventory_numbers';
  const MAX_VISIBLE_ROWS=1000;
  const COUNTERS=[
    ['total','Всего'],
    ['success','SUCCESS'],
    ['unchanged','UNCHANGED'],
    ['not_found','NOT_FOUND'],
    ['already_assigned','ALREADY_ASSIGNED'],
    ['duplicate_inventory_number','DUPLICATE_INVENTORY_NUMBER'],
    ['validation_error','VALIDATION_ERROR']
  ];
  const STATUS_CLASSES={
    SUCCESS:'success',
    UNCHANGED:'unchanged',
    NOT_FOUND:'not-found',
    ALREADY_ASSIGNED:'already-assigned',
    DUPLICATE_INVENTORY_NUMBER:'duplicate-inventory-number',
    VALIDATION_ERROR:'validation-error'
  };

  const input=document.getElementById('inventoryNumberCsv');
  const output=document.getElementById('inventoryNumberImport');
  let previewId='';
  let requestSequence=0;
  let confirming=false;

  function canWrite(){
    return ['admin','engineer'].includes(state?.current_user?.role);
  }

  function countValue(result,key){
    const value=Number(result?.[key]||0);
    return Number.isFinite(value)?value:0;
  }

  function statusBadge(status){
    const value=String(status||'VALIDATION_ERROR');
    const suffix=STATUS_CLASSES[value]||'validation-error';
    return renderBadge(value,`inventory-number-status inventory-number-status-${suffix}`);
  }

  function resultRow(row){
    return renderElement('tr',{children:[
      renderElement('td',{text:row.line??''}),
      renderElement('td',{text:row.serial_number||''}),
      renderElement('td',{text:row.inventory_number||''}),
      renderElement('td',{text:row.current_inventory_number||'—'}),
      renderElement('td',{children:[statusBadge(row.status)]}),
      renderElement('td',{className:'inventory-number-message',text:row.message||''})
    ]});
  }

  function showOutput(phase){
    if(!output)return;
    output.classList.add('show','inventory-number-import');
    output.dataset.phase=phase;
  }

  function renderLoading(){
    if(!output)return;
    showOutput('loading');
    output.replaceChildren(renderElement('div',{
      className:'inventory-number-state',attrs:{role:'status'},text:'Проверяем CSV...'
    }));
  }

  function renderError(error){
    if(!output)return;
    previewId='';
    showOutput('error');
    output.replaceChildren(renderElement('div',{
      className:'inventory-number-state error-list',attrs:{role:'alert'},
      text:error?.message||'Не удалось проверить CSV'
    }));
  }

  function renderResult(result,phase='preview'){
    if(!output)return;
    const rows=Array.isArray(result?.rows)?result.rows:[];
    const errors=Array.isArray(result?.errors)?result.errors:[];
    const visibleRows=rows.slice(0,MAX_VISIBLE_ROWS);
    const isPreview=phase==='preview';
    previewId=isPreview?String(result?.preview_id||''):'';
    showOutput(phase);

    const summary=renderElement('div',{className:'inventory-number-summary',children:COUNTERS.map(([key,label])=>
      renderCard({title:label,value:countValue(result,key).toLocaleString('ru-RU'),className:'inventory-number-summary-card'})
    )});
    const table=renderTable({
      headers:['Строка','Serial Number','Inventory Number','Текущий Inventory Number','Статус','Сообщение'],
      rows:visibleRows,
      empty:'В CSV нет строк для отображения',
      rowRenderer:resultRow,
      className:'inventory-number-table'
    });
    const children=[
      renderElement('div',{className:'inventory-number-head',children:[
        renderElement('h3',{text:isPreview?'Предпросмотр назначения Inventory Number':'Результат импорта'}),
        renderElement('p',{className:'hint',text:isPreview
          ?(result?.can_confirm
            ?'Предпросмотр не изменил базу. Проверьте строки и подтвердите импорт.'
            :'CSV содержит ошибку валидации. Подтверждение импорта недоступно.')
          :'Импорт завершён. В таблице показан итог для каждой строки.'})
      ]}),
      summary
    ];
    if(errors.length){
      children.push(renderElement('ul',{className:'error-list inventory-number-errors',children:errors.map(error=>
        renderElement('li',{text:`Строка ${error.line??'—'}: ${error.reason||'Ошибка валидации'}`})
      )}));
    }
    children.push(renderElement('div',{className:'table-wrap inventory-number-table-wrap',children:[table]}));
    if(rows.length>visibleRows.length){
      children.push(renderElement('p',{className:'hint',text:`Показаны первые ${visibleRows.length} из ${rows.length} строк.`}));
    }

    if(isPreview&&canWrite()){
      const canConfirm=result?.can_confirm===true&&Boolean(previewId);
      const confirmButton=renderButton({
        text:'Подтвердить импорт',
        className:'button inventory-number-confirm',
        primary:true,
        disabled:!canConfirm,
        onClick:()=>confirmPreview(confirmButton)
      });
      children.push(renderElement('div',{className:'inventory-number-actions',children:[confirmButton]}));
    }
    output.replaceChildren(...children);
  }

  async function previewFile(file){
    if(!file||!output)return;
    if(!canWrite()){
      renderError(new Error('Недостаточно прав для импорта'));
      return;
    }
    const sequence=++requestSequence;
    previewId='';
    if(input)input.disabled=true;
    renderLoading();
    try{
      const result=await request(`/api/preview-csv?kind=${KIND}`,{
        method:'POST',
        headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(file.name)},
        body:file
      });
      if(sequence!==requestSequence)return;
      renderResult(result,'preview');
      notify(result.can_confirm?'CSV проверен, можно подтвердить':'CSV содержит ошибку валидации',!result.can_confirm);
    }catch(error){
      if(sequence===requestSequence){renderError(error);notify(error.message,true)}
    }finally{
      if(sequence===requestSequence&&input){input.disabled=false;input.value=''}
    }
  }

  async function confirmPreview(button){
    if(confirming||!previewId)return;
    confirming=true;
    button.disabled=true;
    if(input)input.disabled=true;
    const selectedPreviewId=previewId;
    try{
      const result=await actionJson({
        action:'CONFIRM_IMPORT_PREVIEW',kind:KIND,preview_id:selectedPreviewId
      });
      previewId='';
      renderResult(result,'result');
      notify(`Назначено Inventory Number: ${countValue(result,'success').toLocaleString('ru-RU')}`);
      await loadAll();
    }catch(error){
      notify(error.message,true);
      if(previewId===selectedPreviewId)button.disabled=false;
    }finally{
      confirming=false;
      if(input)input.disabled=false;
    }
  }

  function handleFileSelection(){
    const file=input?.files?.[0];
    if(file)previewFile(file);
  }

  if(input&&output)input.addEventListener('change',handleFileSelection);
  window.ODE.warehouse.inventory={
    legacy:true,
    kind:KIND,
    previewFile,
    renderResult,
    isReady:()=>Boolean(input&&output)
  };
})();
