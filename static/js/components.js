function appendChildren(parent, children=[]){
  for(const child of children.flat()){
    if(child===null||child===undefined||child===false)continue;
    parent.appendChild(child instanceof Node?child:document.createTextNode(String(child)));
  }
  return parent;
}
function renderElement(tag,{className='',attrs={},dataset={},text='',children=[],on={}}={}){
  const node=document.createElement(tag);
  if(className)node.className=className;
  for(const [key,value] of Object.entries(attrs)){
    if(value===false||value===null||value===undefined)continue;
    if(value===true)node.setAttribute(key,'');
    else node.setAttribute(key,String(value));
  }
  for(const [key,value] of Object.entries(dataset))node.dataset[key]=String(value);
  for(const [event,handler] of Object.entries(on))node.addEventListener(event,handler);
  if(text!==''&&text!==null&&text!==undefined)node.textContent=String(text);
  appendChildren(node,children);
  return node;
}
function renderButton({text='',className='button',type='button',primary=false,disabled=false,dataset={},onClick=null,children=[]}={}){
  return renderElement('button',{className:primary?`${className} primary`:className,attrs:{type,disabled},dataset,children:children.length?children:[text],on:onClick?{click:onClick}:{}})
}
function renderCard({title='',value='',className='card',children=[]}={}){
  const body=children.length?children:[renderElement('span',{text:title}),renderElement('strong',{text:value})];
  return renderElement('div',{className,children:body});
}
function renderInput({name='',id='',type='text',value='',placeholder='',required=false,readOnly=false,className='',attrs={}}={}){
  const input=renderElement('input',{className,attrs:{...attrs,name,id,type,value,placeholder,required,readonly:readOnly}});
  return input;
}
function renderSelect({name='',id='',className='',value='',options=[],required=false,onChange=null}={}){
  const select=renderElement('select',{className,attrs:{name,id,required},on:onChange?{change:onChange}:{}});
  select.replaceChildren(...options.map(item=>{
    const optionNode=document.createElement('option');
    const optionValue=Array.isArray(item)?item[0]:item;
    const label=Array.isArray(item)?item[1]:item;
    optionNode.value=String(optionValue??'');
    optionNode.textContent=String(label??optionValue??'');
    if(String(optionValue??'')===String(value??''))optionNode.selected=true;
    return optionNode;
  }));
  return select;
}
function renderBadge(text,className='badge'){return renderElement('span',{className,text})}
function renderSvgIcon(pathData,{className='',attrs={}}={}){
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox',attrs.viewBox||'0 0 24 24');
  svg.setAttribute('aria-hidden','true');
  if(className)svg.setAttribute('class',className);
  const path=document.createElementNS('http://www.w3.org/2000/svg','path');
  path.setAttribute('d',pathData);
  svg.appendChild(path);
  return svg;
}
function renderTable({headers=[],rows=[],empty='Нет данных',rowRenderer=null,className=''}={}){
  const table=renderElement('table',{className});
  const thead=renderElement('thead');
  const headRow=renderElement('tr');
  headRow.replaceChildren(...headers.map(header=>renderElement('th',{text:header})));
  thead.appendChild(headRow);
  const tbody=renderElement('tbody');
  if(rows.length){
    tbody.replaceChildren(...rows.map(row=>rowRenderer?rowRenderer(row):renderElement('tr',{children:headers.map(header=>renderElement('td',{text:row[header]??''}))})));
  }else{
    tbody.appendChild(renderElement('tr',{children:[renderElement('td',{className:'empty',attrs:{colspan:Math.max(headers.length,1)},text:empty})]}));
  }
  table.replaceChildren(thead,tbody);
  return table;
}
function renderToast(message,error=false){return renderElement('div',{className:`status show${error?' error':''}`,text:message})}
function renderDialog({title='',children=[]}={}){return renderElement('div',{className:'modal-card',children:[renderElement('div',{className:'modal-head',children:[renderElement('h2',{text:title})]}),...children]})}
// Styled replacement for window.confirm: returns a Promise<boolean> resolved
// when the user confirms (true) or cancels/dismisses (false). Looks like part
// of the site (uses the shared .modal styling) instead of a browser dialog.
function confirmDialog({title='Подтверждение',message='',confirmText='Подтвердить',cancelText='Отмена',danger=false}={}){
  return new Promise(resolve=>{
    const overlay=renderElement('div',{className:'modal show confirm-modal'});
    let settled=false;
    const close=result=>{
      if(settled)return;
      settled=true;
      document.removeEventListener('keydown',onKey);
      overlay.remove();
      resolve(result);
    };
    const onKey=event=>{
      if(event.key==='Escape')close(false);
    };
    const confirmBtn=renderButton({text:confirmText,className:danger?'button danger':'button primary',onClick:()=>close(true)});
    const cancelBtn=renderButton({text:cancelText,className:'button',onClick:()=>close(false)});
    const card=renderElement('div',{className:'modal-card confirm-card',children:[
      renderElement('div',{className:'modal-head',children:[renderElement('h3',{text:title})]}),
      renderElement('p',{className:'confirm-message',text:message}),
      renderElement('div',{className:'confirm-actions',children:[cancelBtn,confirmBtn]}),
    ]});
    overlay.appendChild(card);
    // Click on the dark backdrop (outside the card) cancels.
    overlay.addEventListener('click',event=>{if(event.target===overlay)close(false)});
    document.addEventListener('keydown',onKey);
    document.body.appendChild(overlay);
    confirmBtn.focus();
  });
}
