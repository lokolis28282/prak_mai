function goHome(){
  showSection('home');
  showView('home');
  window.scrollTo(0,0);
}

function initSectionNavigation(){
  const nav=document.querySelector('.section-nav');
  if(!nav)return;
  nav.replaceChildren();
  nav.hidden=true;
  nav.setAttribute('aria-hidden','true');
}

function showSection(name){
  const entries=sections[name];
  if(!entries||!entries.length){showPlaceholder(name);return}
  currentSection=name;
  setText('pageTitle',{home:'ODE',monitoring:'Мониторинг',knowledge:'База знаний',works:'Работы',warehouse:'Склад',reports:'Отчеты',administration:'Администрирование',profile:'Профиль'}[name]||'Раздел');
  const nav=byId('subnav');
  nav.style.display=['warehouse','works','reports','administration'].includes(name)?'flex':'none';
  nav.replaceChildren(...entries.map((entry,index)=>renderButton({
    text:entry[1],
    className:`subtab ${index?'':'active'}`,
    dataset:{view:entry[0]},
    onClick:()=>showView(entry[0])
  })));
  showView(entries[0][0]);
  if(name==='knowledge')window.ODE?.knowledge?.renderRoute();
}
function showView(id){
  const adminMode=id.startsWith('admin_')?id:'';
  const actual=id==='admin_references'?'references':adminMode?'admin':id;
  document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===actual));
  document.querySelectorAll('.subtab').forEach(x=>x.classList.toggle('active',x.dataset.view===id));
  if(id==='worklogs')loadWorkLogs();
  if(id==='admin_references'){window.renderReferenceEditor?.();return}
  if(id==='daily'&&typeof buildShift==='function')buildShift();
  if(id==='weekly'&&typeof buildWeek==='function')buildWeek();
  if(adminMode){setAdminMode(adminMode);loadAdmin()}
  if(id==='deliveries')loadDeliveries();
}
function openTask(section,view){showSection(section);showView(view)}
function setAdminMode(mode){
  const root=byId('admin'),split=root.querySelector('.split'),boxes=[...split.children],direct=[...root.children];
  direct.forEach(x=>x.style.display='none');
  root.querySelector('h2').style.display='block';
  root.querySelector('p').style.display='block';
  boxes.forEach(x=>x.style.display='none');
  const heads=[...root.querySelectorAll(':scope > h3')],tables=[...root.querySelectorAll(':scope > .table-wrap')];
  if(mode==='admin_users'){split.style.display='grid';boxes[3].style.display='block';heads[0].style.display='block';tables[0].style.display='block'}
  if(mode==='admin_backups'){split.style.display='grid';boxes[0].style.display='block';boxes[1].style.display='block';boxes[2].style.display='block';heads[1].style.display='block';tables[1].style.display='block'}
  if(mode==='admin_database'){split.style.display='grid';boxes[0].style.display='block'}
  if(mode==='admin_audit'){heads[2].style.display='block';tables[2].style.display='block'}
  if(mode==='admin_permissions'){split.style.display='grid';boxes[3].style.display='block';heads[0].style.display='block';tables[0].style.display='block'}
  if(mode==='admin_migration'){root.querySelector('p').textContent='Миграционная диагностиика доступна в административном контексте и не показывается инженерам.'}
}
function showProfile(){
  document.querySelectorAll('.section-button').forEach(x=>x.classList.remove('active'));
  setText('pageTitle','Профиль');
  const nav=byId('subnav');if(nav)nav.style.display='none';
  showView('profile');
}
initSectionNavigation();
