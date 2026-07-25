(function(){
  const rootApi='/api/knowledge';
  const categories={
    instructions:{label:'Инструкции',icon:'И',description:'Рабочие инструкции, регламенты и порядок действий дежурного инженера.'},
    specifications:{label:'Спецификации',icon:'С',description:'Технические характеристики и документация по оборудованию.'}
  };
  const allowedExtensions=new Set(['pdf','docx','xlsx','txt','png','jpg','jpeg']);
  const filters={instructions:{query:'',tag:'',page:1},specifications:{query:'',tag:'',page:1}};
  let activeRoute='home';

  function canEdit(){return ['admin','engineer'].includes(String(state.current_user?.role||''))}
  function routeFromHash(parts){
    const values=(parts||[]).filter(Boolean);
    if(!values.length||values[0]==='knowledge'||values[0]==='home')return 'home';
    if(categories[values[0]])return values[0];
    if(values[0]==='article'&&/^\d+$/.test(values[1]||''))return `article/${values[1]}`;
    if(values[0]==='create'&&categories[values[1]])return `create/${values[1]}`;
    if(values[0]==='edit'&&/^\d+$/.test(values[1]||''))return `edit/${values[1]}`;
    return 'not-found';
  }
  function routeFromLocation(){
    if(history.state?.section==='knowledge'&&history.state?.knowledgeRoute)return history.state.knowledgeRoute;
    const parts=location.hash.replace(/^#/,'').split('/').map(decodeURIComponent);
    return parts[0]==='knowledge'?routeFromHash(parts.slice(1)):'home';
  }
  function routeHash(route){return '#knowledge/'+route.split('/').map(encodeURIComponent).join('/')}
  function navigate(route,replace=false){
    activeRoute=route;
    const target={section:'knowledge',view:'knowledge',knowledgeRoute:route};
    history[replace?'replaceState':'pushState'](target,'',routeHash(route));
    if(currentSection!=='knowledge')showSection('knowledge');
    else renderRoute(route);
    window.scrollTo(0,0);
  }
  function pageRoot(){return byId('knowledge')}
  function formatDate(value){
    if(!value)return 'Не указана';
    const date=new Date(String(value).replace(' ','T'));
    return Number.isNaN(date.getTime())?String(value):date.toLocaleString('ru-RU',{dateStyle:'medium',timeStyle:'short'});
  }
  function formatSize(value){
    const bytes=Number(value)||0;
    if(bytes<1024)return `${bytes} Б`;
    if(bytes<1024*1024)return `${(bytes/1024).toFixed(1)} КБ`;
    return `${(bytes/1024/1024).toFixed(1)} МБ`;
  }
  function breadcrumb(items){
    return renderElement('nav',{className:'knowledge-breadcrumb',attrs:{'aria-label':'Навигационная цепочка'},children:items.flatMap((item,index)=>[
      index?renderElement('span',{attrs:{'aria-hidden':'true'},text:'›'}):null,
      item.onClick?renderButton({text:item.label,className:'knowledge-crumb',onClick:item.onClick}):renderElement('span',{className:'knowledge-crumb current',text:item.label})
    ])});
  }
  function titleBlock(eyebrow,title,description,actions=[]){
    return renderElement('div',{className:'knowledge-page-head',children:[
      renderElement('div',{children:[renderElement('p',{className:'eyebrow',text:eyebrow}),renderElement('h2',{text:title}),description?renderElement('p',{text:description}):null]}),
      actions.length?renderElement('div',{className:'knowledge-head-actions',children:actions}):null
    ]});
  }
  function tagList(tags){
    if(!tags?.length)return null;
    return renderElement('div',{className:'knowledge-tags',children:tags.map(tag=>renderElement('span',{text:tag}))});
  }
  function toolCard(category){
    const item=categories[category];
    return renderElement('button',{className:'monitoring-tool-launcher knowledge-tool-card',attrs:{type:'button','aria-label':`Открыть раздел ${item.label}`},on:{click:()=>navigate(category)},children:[
      renderElement('span',{className:'monitoring-tool-icon',attrs:{'aria-hidden':'true'},text:item.icon}),
      renderElement('span',{className:'monitoring-tool-copy',children:[renderElement('small',{text:'База знаний'}),renderElement('strong',{text:item.label}),renderElement('span',{text:item.description})]}),
      renderElement('span',{className:'monitoring-tool-open',attrs:{'aria-hidden':'true'},text:'Открыть →'})
    ]});
  }
  function renderHub(){
    const root=pageRoot();if(!root)return;
    root.replaceChildren(renderElement('div',{className:'knowledge-shell knowledge-hub',children:[
      titleBlock('База знаний','База знаний','Инструкции, статьи и техническая документация для дежурных инженеров.'),
      renderElement('div',{className:'knowledge-tool-list',children:[toolCard('instructions'),toolCard('specifications')]}),
      renderButton({text:'← На главный экран',className:'button knowledge-home-back',onClick:goHome})
    ]}));
  }
  function loading(){
    const root=pageRoot();if(root)root.replaceChildren(renderElement('div',{className:'knowledge-loading',attrs:{role:'status'},text:'Загрузка базы знаний...'}));
  }
  function renderError(message,onBack=()=>navigate('home')){
    const root=pageRoot();if(!root)return;
    root.replaceChildren(renderElement('div',{className:'knowledge-shell',children:[
      breadcrumb([{label:'База знаний',onClick:()=>navigate('home')},{label:'Ошибка'}]),
      renderElement('div',{className:'knowledge-empty error-list',children:[renderElement('h2',{text:'Не удалось открыть страницу'}),renderElement('p',{text:message||'Произошла ошибка'}),renderButton({text:'Вернуться',className:'button',onClick:onBack})]})
    ]}));
  }
  function articleCard(article){
    const meta=[article.updated_at?`Обновлено ${formatDate(article.updated_at)}`:'',article.attachment_count?`Файлов: ${article.attachment_count}`:''].filter(Boolean).join(' · ');
    return renderElement('button',{className:'monitoring-tool-launcher knowledge-article-card',attrs:{type:'button'},on:{click:()=>navigate(`article/${article.id}`)},children:[
      renderElement('span',{className:'monitoring-tool-icon',attrs:{'aria-hidden':'true'},text:'Д'}),
      renderElement('span',{className:'monitoring-tool-copy',children:[
        renderElement('small',{text:article.category_label}),renderElement('strong',{text:article.title}),
        renderElement('span',{text:article.summary||'Без краткого описания'}),tagList(article.tags),
        meta?renderElement('span',{className:'knowledge-card-meta',text:meta}):null
      ]}),
      renderElement('span',{className:'monitoring-tool-open',attrs:{'aria-hidden':'true'},text:'Открыть →'})
    ]});
  }
  function categoryControls(category,data){
    const current=filters[category];
    const query=renderElement('input',{attrs:{type:'search',value:current.query,placeholder:'Поиск по статьям','aria-label':'Поиск по статьям'}});
    const tag=renderSelect({value:current.tag,options:[['','Все теги'],...(data.tags||[]).map(value=>[value,value])]});
    const submit=renderButton({text:'Найти',className:'button primary',type:'submit'});
    return renderElement('form',{className:'knowledge-filters',children:[query,tag,submit,current.query||current.tag?renderButton({text:'Сбросить',className:'button',onClick:()=>{filters[category]={query:'',tag:'',page:1};renderCategory(category)}}):null],on:{submit:event=>{
      event.preventDefault();filters[category]={query:query.value.trim(),tag:tag.value,page:1};renderCategory(category);
    }}});
  }
  function categoryPager(category,data){
    if(Number(data.pages||1)<=1)return null;
    return renderElement('div',{className:'knowledge-pager',children:[
      renderButton({text:'← Предыдущая',className:'button',disabled:data.page<=1,onClick:()=>{filters[category].page=data.page-1;renderCategory(category)}}),
      renderElement('span',{text:`Страница ${data.page} из ${data.pages} · материалов: ${data.total}`}),
      renderButton({text:'Следующая →',className:'button',disabled:data.page>=data.pages,onClick:()=>{filters[category].page=data.page+1;renderCategory(category)}})
    ]});
  }
  async function renderCategory(category){
    const item=categories[category];if(!item){renderError('Категория не найдена');return}
    loading();
    try{
      const current=filters[category];
      const params=new URLSearchParams({category,query:current.query,tag:current.tag,page:String(current.page),page_size:'20'});
      const data=await request(`${rootApi}/articles?${params}`);
      if(activeRoute!==category)return;
      const root=pageRoot();
      const actions=canEdit()?[renderButton({text:'Создать статью',className:'button primary',onClick:()=>navigate(`create/${category}`)})]:[];
      const articles=data.articles||[];
      const list=articles.length?renderElement('div',{className:'knowledge-article-list',children:articles.map(articleCard)}):renderElement('div',{className:'knowledge-empty',children:[
        renderElement('h3',{text:'Материалы не найдены'}),renderElement('p',{text:'Измените условия поиска или создайте новую статью.'}),
        canEdit()?renderButton({text:'Создать статью',className:'button primary',onClick:()=>navigate(`create/${category}`)}):null
      ]});
      root.replaceChildren(renderElement('div',{className:'knowledge-shell',children:[
        breadcrumb([{label:'База знаний',onClick:()=>navigate('home')},{label:item.label}]),
        titleBlock('База знаний',item.label,item.description,actions),categoryControls(category,data),list,categoryPager(category,data),
        renderButton({text:'← В базу знаний',className:'button knowledge-list-back',onClick:()=>navigate('home')})
      ]}));
    }catch(error){renderError(error.message,()=>navigate('home'))}
  }
  function field(label,control,wide=false){
    return renderElement('label',{className:`knowledge-field${wide?' wide':''}`,children:[renderElement('span',{text:label}),control]});
  }
  async function uploadFiles(articleId,files){
    const failed=[];
    for(const file of files){
      try{await request(`${rootApi}/articles/${articleId}/attachments`,{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream','X-Filename':encodeURIComponent(file.name)},body:file})}
      catch(error){failed.push(`${file.name}: ${error.message}`)}
    }
    return failed;
  }
  function renderEditor(category,article=null){
    const item=categories[category];if(!item){renderError('Категория не найдена');return}
    if(!canEdit()){renderError('Недостаточно прав для изменения статей',()=>navigate(category));return}
    const title=renderElement('input',{attrs:{name:'title',maxlength:'200',required:true,autocomplete:'off',value:article?.title||''}});
    const summary=renderElement('textarea',{attrs:{name:'summary',maxlength:'1000',rows:'3'},text:article?.summary||''});
    const tags=renderElement('input',{attrs:{name:'tags',maxlength:'500',autocomplete:'off',placeholder:'серверы, сеть, аварии',value:(article?.tags||[]).join(', ')}});
    const content=renderElement('textarea',{className:'knowledge-editor',attrs:{name:'content',maxlength:'250000',rows:'16',required:true,spellcheck:'true'},text:article?.content||''});
    const select=renderSelect({name:'category',value:category,required:true,options:[['instructions','Инструкции'],['specifications','Спецификации']]});
    const files=renderElement('input',{attrs:{name:'attachments',type:'file',multiple:true,accept:'.pdf,.docx,.xlsx,.txt,.png,.jpg,.jpeg'}});
    const errorBox=renderElement('div',{className:'knowledge-form-error',attrs:{role:'alert'}});
    const save=renderButton({text:article?'Сохранить изменения':'Сохранить',className:'button primary',type:'submit'});
    const cancelRoute=article?`article/${article.id}`:category;
    const form=renderElement('form',{className:'knowledge-form',children:[
      field('Название статьи',title,true),field('Краткое описание',summary,true),field('Категория',select),field('Теги через запятую',tags),
      field('Добавить документы',files,true),field('Основной текст (Markdown)',content,true),
      renderElement('p',{className:'knowledge-markdown-help',text:'Поддерживаются заголовки, списки, жирный и курсивный текст, ссылки и блоки кода.'}),
      errorBox,renderElement('div',{className:'knowledge-form-actions',children:[save,renderButton({text:'Отмена',className:'button',onClick:()=>navigate(cancelRoute)})]})
    ],on:{submit:async event=>{
      event.preventDefault();errorBox.textContent='';
      const selected=[...files.files];
      const invalid=selected.find(file=>!allowedExtensions.has((file.name.split('.').pop()||'').toLocaleLowerCase())||file.size>15*1024*1024);
      if(invalid){errorBox.textContent=`Файл «${invalid.name}» имеет запрещенный тип или превышает 15 МБ.`;return}
      save.disabled=true;save.textContent='Сохранение...';
      try{
        const payload={title:title.value,summary:summary.value,content:content.value,category:select.value,tags:tags.value.split(',').map(value=>value.trim()).filter(Boolean)};
        const response=await request(article?`${rootApi}/articles/${article.id}`:`${rootApi}/articles`,{method:article?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const saved=response.article;
        const failed=await uploadFiles(saved.id,selected);
        navigate(`article/${saved.id}`);
        notify(failed.length?`Статья сохранена. Не загружено файлов: ${failed.length}`:'Статья успешно сохранена',Boolean(failed.length));
      }catch(error){errorBox.textContent=error.message;save.disabled=false;save.textContent=article?'Сохранить изменения':'Сохранить'}
    }}});
    const root=pageRoot();
    root.replaceChildren(renderElement('div',{className:'knowledge-shell',children:[
      breadcrumb([{label:'База знаний',onClick:()=>navigate('home')},{label:item.label,onClick:()=>navigate(category)},{label:article?'Редактирование':'Новая статья'}]),
      titleBlock('База знаний',article?'Редактировать статью':'Создать статью',`Раздел «${item.label}».`),form
    ]}));
    title.focus();
  }
  async function renderEdit(id){
    loading();
    try{
      const data=await request(`${rootApi}/articles/${encodeURIComponent(id)}`);
      if(activeRoute!==`edit/${id}`)return;
      renderEditor(data.article.category,data.article);
    }catch(error){renderError(error.message,()=>navigate('home'))}
  }
  async function deleteArticle(article){
    if(!window.confirm(`Удалить статью «${article.title}»?`))return;
    try{
      await request(`${rootApi}/articles/${article.id}`,{method:'DELETE'});
      notify('Статья удалена');navigate(article.category);
    }catch(error){notify(error.message,true)}
  }
  async function renderArticle(id){
    loading();
    try{
      const data=await request(`${rootApi}/articles/${encodeURIComponent(id)}`);
      if(activeRoute!==`article/${id}`)return;
      const article=data.article,item=categories[article.category];
      const content=renderElement('div',{className:'knowledge-markdown'});
      content.replaceChildren(htmlFragment(article.content_html||''));
      const attachments=article.attachments||[];
      const attachmentBlock=attachments.length?renderElement('section',{className:'knowledge-attachments',children:[
        renderElement('h3',{text:'Прикрепленные документы'}),
        renderElement('div',{className:'knowledge-attachment-list',children:attachments.map(file=>renderElement('a',{className:'knowledge-attachment',attrs:{href:file.download_url},children:[
          renderElement('span',{attrs:{'aria-hidden':'true'},text:'Ф'}),renderElement('strong',{text:file.original_name}),renderElement('small',{text:`${file.content_type} · ${formatSize(file.size_bytes)}`}),renderElement('b',{text:'Скачать'})
        ]}))})
      ]}):null;
      const actions=canEdit()?renderElement('div',{className:'knowledge-article-actions',children:[
        renderButton({text:'Редактировать',className:'button',onClick:()=>navigate(`edit/${article.id}`)}),
        renderButton({text:'Удалить',className:'button danger',onClick:()=>deleteArticle(article)})
      ]}):null;
      const root=pageRoot();
      root.replaceChildren(renderElement('div',{className:'knowledge-shell knowledge-article-page',children:[
        breadcrumb([{label:'База знаний',onClick:()=>navigate('home')},{label:item.label,onClick:()=>navigate(article.category)},{label:article.title}]),
        renderElement('article',{className:'knowledge-wiki',children:[
          renderElement('p',{className:'eyebrow',text:item.label}),renderElement('h1',{text:article.title}),
          article.summary?renderElement('p',{className:'knowledge-summary',text:article.summary}):null,tagList(article.tags),
          renderElement('div',{className:'knowledge-meta',children:[renderElement('span',{text:`Создано: ${formatDate(article.created_at)}`}),renderElement('span',{text:`Обновлено: ${formatDate(article.updated_at)}`}),renderElement('span',{text:`Автор: ${article.author_name}`})]}),
          actions,content,attachmentBlock
        ]}),
        renderButton({text:`← К разделу «${item.label}»`,className:'button knowledge-list-back',onClick:()=>navigate(article.category)})
      ]}));
    }catch(error){renderError(error.message,()=>navigate('home'))}
  }
  function renderRoute(route=routeFromLocation()){
    activeRoute=route||'home';setText('pageTitle','База знаний');
    if(activeRoute==='home')renderHub();
    else if(categories[activeRoute])renderCategory(activeRoute);
    else if(/^article\/\d+$/.test(activeRoute))renderArticle(activeRoute.split('/')[1]);
    else if(/^create\/(instructions|specifications)$/.test(activeRoute))renderEditor(activeRoute.split('/')[1]);
    else if(/^edit\/\d+$/.test(activeRoute))renderEdit(activeRoute.split('/')[1]);
    else renderError('Страница базы знаний не найдена');
  }

  window.ODE=window.ODE||{};
  window.ODE.knowledge={navigate,renderRoute,routeFromHash};
  window.openKnowledgeBase=()=>navigate('home');
})();
