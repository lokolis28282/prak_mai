(function(){
  const PAGE_SIZE=100;
  const LEVEL_DEPTH={category:0,item_type:1,vendor:2,model:3};
  const FILTER_IDS=[
    'balanceQuery','uxBalanceCategory','uxBalanceType','uxBalanceProject',
    'uxBalanceSupplier','uxBalanceVendor','uxBalanceStock','uxBalanceSort'
  ];
  const cache=new Map(),expanded=new Set(),pending=new Map();
  let rootNodes=[],total={positions:0,available:0},attached=false,invalidated=true;
  let generation=0,debounceTimer=0,rootError='',rootLoading=false;

  const number=value=>Number(value||0).toLocaleString('ru-RU',{
    maximumFractionDigits:Number.isInteger(Number(value||0))?0:3
  });
  const balanceViewActive=()=>document.getElementById('balance')?.classList.contains('active');

  function filterParams(){
    const sort=(document.getElementById('uxBalanceSort')?.value||'item_name:asc').split(':');
    return new URLSearchParams({
      query:document.getElementById('balanceQuery')?.value.trim()||'',
      category:document.getElementById('uxBalanceCategory')?.value||'',
      item_type:document.getElementById('uxBalanceType')?.value||'',
      project:document.getElementById('uxBalanceProject')?.value||'',
      supplier:document.getElementById('uxBalanceSupplier')?.value||'',
      vendor:document.getElementById('uxBalanceVendor')?.value||'',
      stock_state:document.getElementById('uxBalanceStock')?.value||'',
      sort_by:sort[0]||'item_name',sort_dir:sort[1]||'asc'
    });
  }

  function activeConditions(){
    const params=filterParams();
    return [...params.entries()].some(([key,value])=>
      value&&!['sort_by','sort_dir'].includes(key)
    );
  }

  function ensureHeader(){
    const head=document.querySelector('#warehouseStockTree thead');
    if(!head)return;
    head.replaceChildren(renderElement('tr',{children:[
      renderElement('th',{text:'Группа'}),
      renderElement('th',{text:'Позиций'}),
      renderElement('th',{text:'В наличии'})
    ]}));
  }

  function statusRow(text,busy=false,retry=null,depth=0){
    const children=[renderElement('span',{text})];
    if(retry)children.push(renderButton({text:'Повторить',className:'button',onClick:retry}));
    const cell=renderElement('td',{className:'warehouse-stock-tree-state',attrs:{colspan:3},children});
    cell.style.setProperty('--tree-depth',String(depth));
    return renderElement('tr',{
      className:busy?'warehouse-stock-tree-loading':'warehouse-stock-tree-message',
      children:[cell]
    });
  }

  function totalRow(){
    return renderElement('tr',{className:'warehouse-stock-tree-total',children:[
      renderElement('th',{scope:'row',text:'Общий итог'}),
      renderElement('td',{text:number(total.positions)}),
      renderElement('td',{text:number(total.available)})
    ]});
  }

  function treeCell(node,depth){
    const cell=renderElement('td',{className:'warehouse-stock-tree-name'});
    cell.style.setProperty('--tree-depth',String(depth));
    if(node.has_children&&node.next_level){
      const isExpanded=expanded.has(node.id);
      const button=renderElement('button',{
        className:'warehouse-stock-tree-toggle',
        attrs:{
          type:'button','aria-expanded':isExpanded?'true':'false',
          'aria-label':`${isExpanded?'Свернуть':'Раскрыть'} группу ${node.label}`
        },
        on:{click:event=>{event.stopPropagation();toggle(node)}}
      });
      button.append(
        renderElement('span',{className:'warehouse-stock-tree-arrow','aria-hidden':'true',text:isExpanded?'▾':'▸'}),
        renderElement('span',{className:'warehouse-stock-tree-label',text:node.label||'Не указано'})
      );
      cell.appendChild(button);
    }else{
      cell.append(
        renderElement('span',{className:'warehouse-stock-tree-terminal-marker','aria-hidden':'true',text:'•'}),
        renderElement('span',{className:'warehouse-stock-tree-label warehouse-stock-tree-terminal',text:node.label||'Не указано'})
      );
    }
    return cell;
  }

  function nodeRow(node,depth){
    return renderElement('tr',{
      className:`warehouse-stock-tree-row warehouse-stock-tree-${node.kind}`,
      attrs:{'data-level':node.level,'data-node-id':node.id},
      children:[
        treeCell(node,depth),
        renderElement('td',{className:'warehouse-stock-tree-number',text:number(node.positions)}),
        renderElement('td',{className:'warehouse-stock-tree-number',text:number(node.available)})
      ]
    });
  }

  function loadMoreRow(parent,entry,depth){
    const label=`Показать ещё (${number(entry.nodes.length)} из ${number(entry.nodeCount)})`;
    const cell=renderElement('td',{attrs:{colspan:3},children:[
      renderButton({text:label,className:'button warehouse-stock-tree-more',onClick:()=>loadChildren(parent,true)})
    ]});
    cell.style.setProperty('--tree-depth',String(depth));
    return renderElement('tr',{className:'warehouse-stock-tree-pagination',children:[cell]});
  }

  function appendBranch(rows,node,depth){
    rows.push(nodeRow(node,depth));
    if(!node.has_children||!node.next_level||!expanded.has(node.id))return;
    const entry=cache.get(node.id);
    if(!entry){rows.push(statusRow('Загрузка ветви...',true,null,depth+1));return}
    if(entry.error){
      rows.push(statusRow('Не удалось загрузить эту ветвь.',false,()=>loadChildren(node),depth+1));
      return;
    }
    if(!entry.nodes.length){rows.push(statusRow('В этой группе нет позиций.',false,null,depth+1));return}
    entry.nodes.forEach(child=>appendBranch(rows,child,depth+1));
    if(entry.hasMore)rows.push(loadMoreRow(node,entry,depth+1));
  }

  function render(){
    ensureHeader();
    const body=document.getElementById('balanceBody');
    if(!body)return;
    if(!balanceViewActive()){
      body.replaceChildren();
      return;
    }
    if(rootLoading){
      body.replaceChildren(statusRow('Загрузка складских групп...',true));
      body.setAttribute('aria-busy','true');
      return;
    }
    body.setAttribute('aria-busy','false');
    if(rootError){
      body.replaceChildren(statusRow('Не удалось загрузить складские позиции.',false,()=>refresh({clearCache:true})));
      return;
    }
    const rows=[totalRow()];
    rootNodes.forEach(node=>appendBranch(rows,node,0));
    if(!rootNodes.length){
      rows.push(statusRow(activeConditions()?'По заданным условиям складские позиции не найдены.':'Складские позиции не найдены.'));
    }
    body.replaceChildren(...rows);
    setText('balanceLimit',`Показано групп: ${number(rootNodes.length)} · Позиций: ${number(total.positions)} · В наличии: ${number(total.available)}`);
    if(typeof renderBalanceFilterSummary==='function')renderBalanceFilterSummary(total.positions);
    updateExport();
  }

  function requestParams(level,path={},offset=0){
    const params=filterParams();
    params.set('level',level);
    params.set('limit',String(PAGE_SIZE));
    params.set('offset',String(offset));
    Object.entries(path).forEach(([key,value])=>{if(value)params.set(key,value)});
    return params;
  }

  async function refresh({clearCache=true,autoExpand=true}={}){
    attach();
    invalidated=false;
    const requestGeneration=++generation;
    if(clearCache){
      cache.clear();expanded.clear();pending.clear();
      state.balance=[];
    }
    rootError='';rootLoading=true;render();
    try{
      const response=await request('/api/warehouse-stock-tree?'+requestParams('category'));
      if(requestGeneration!==generation)return;
      rootNodes=response.nodes||[];
      total=response.total||{positions:0,available:0};
      rootLoading=false;render();
      const query=document.getElementById('balanceQuery')?.value.trim()||'';
      if(autoExpand&&query&&Number(total.positions)<=50){
        await expandSearchMatches(rootNodes,{remaining:12,generation:requestGeneration});
      }
    }catch(error){
      if(requestGeneration!==generation)return;
      rootLoading=false;rootError=error?.message||'Ошибка загрузки';
      console.error('Warehouse stock tree root loading failed',error);
      render();
    }
  }

  async function loadChildren(node,append=false){
    if(!node.has_children||!node.next_level)return null;
    if(pending.has(node.id))return pending.get(node.id);
    const requestGeneration=generation;
    const previous=cache.get(node.id);
    const offset=append?(previous?.nodes.length||0):0;
    if(!append)cache.delete(node.id);
    render();
    const promise=(async()=>{
      try{
        const response=await request('/api/warehouse-stock-tree?'+requestParams(node.next_level,node.path,offset));
        if(requestGeneration!==generation)return null;
        const known=new Set((append?previous?.nodes:[]||[]).map(child=>child.id));
        const incoming=(response.nodes||[]).filter(child=>!known.has(child.id));
        const nodes=append?[...(previous?.nodes||[]),...incoming]:incoming;
        const entry={nodes,hasMore:Boolean(response.has_more),nodeCount:Number(response.node_count||response.total?.positions||nodes.length),total:response.total||{positions:nodes.length,available:0},error:''};
        cache.set(node.id,entry);render();
        return entry;
      }catch(error){
        if(requestGeneration!==generation)return null;
        cache.set(node.id,{nodes:previous?.nodes||[],hasMore:false,nodeCount:previous?.nodeCount||0,total:previous?.total||{positions:0,available:0},error:error?.message||'Ошибка загрузки'});
        console.error('Warehouse stock tree branch loading failed',error);
        render();
        return null;
      }finally{
        pending.delete(node.id);
      }
    })();
    pending.set(node.id,promise);
    return promise;
  }

  async function toggle(node){
    if(!node.has_children||!node.next_level)return;
    if(expanded.has(node.id)){
      expanded.delete(node.id);render();return;
    }
    expanded.add(node.id);render();
    if(!cache.has(node.id))await loadChildren(node);
  }

  async function expandSearchMatches(nodes,budget){
    if(budget.generation!==generation||budget.remaining<=0)return;
    for(const node of nodes){
      if(budget.generation!==generation||budget.remaining<=0)return;
      if(!node.has_children||!node.next_level)continue;
      expanded.add(node.id);budget.remaining-=1;
      const entry=cache.get(node.id)||await loadChildren(node);
      if(entry?.nodes?.length)await expandSearchMatches(entry.nodes,budget);
    }
    render();
  }

  function updateExport(){
    const link=document.getElementById('balanceExport');
    if(link)link.href='/export/balance.csv?'+filterParams();
  }

  function scheduleRefresh(event){
    clearTimeout(debounceTimer);
    const delay=event?.target?.id==='balanceQuery'?320:0;
    debounceTimer=window.setTimeout(()=>refresh({clearCache:true}),delay);
  }

  function attach(){
    if(attached)return;
    attached=true;ensureHeader();
    FILTER_IDS.map(id=>document.getElementById(id)).filter(Boolean).forEach(control=>{
      control.oninput=null;control.onchange=null;
      control.addEventListener('input',scheduleRefresh);
      control.addEventListener('change',scheduleRefresh);
    });
  }

  function invalidate(){
    invalidated=true;generation+=1;cache.clear();expanded.clear();pending.clear();
    rootNodes=[];total={positions:0,available:0};state.balance=[];
    if(balanceViewActive())refresh({clearCache:true});
  }

  function renderOrLoad(){
    attach();
    if(!balanceViewActive()){document.getElementById('balanceBody')?.replaceChildren();return}
    if(invalidated||(!rootNodes.length&&!rootLoading&&!rootError))refresh({clearCache:false});
    else render();
  }

  const legacyRender=window.renderSimpleBalance;
  window.renderSimpleBalance=function(){
    if(document.getElementById('warehouseStockTree'))renderOrLoad();
    else legacyRender?.();
  };
  window.renderBalanceHeaders=ensureHeader;
  window.warehouseStockTree={attach,refresh,invalidate,render:renderOrLoad,debugState:()=>({
    rootNodes:rootNodes.length,cacheEntries:cache.size,expanded:expanded.size,
    pending:pending.size,total:{...total},generation
  })};
})();
