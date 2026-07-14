function showInterfaceError(error){var box=document.getElementById('interfaceError');if(!box)return;var text=error&&(error.message||error.reason&&error.reason.message||error.reason||error);box.textContent='Ошибка интерфейса: откройте консоль браузера\n'+String(text||'Неизвестная ошибка')+(error&&error.stack?'\n'+error.stack:'');box.hidden=false;}window.addEventListener('error',function(event){showInterfaceError(event.error||event.message)});window.addEventListener('unhandledrejection',function(event){showInterfaceError(event.reason)});

let sections={home:[['home','Главная']],warehouse:[['overview','Обзор'],['receipt','Приход'],['issue','Расход'],['balance','Баланс'],['deliveries','Поставки'],['inventory','Инвентаризация'],['journal','История']],reports:[['worklogs','УВР'],['daily','Отчет за смену'],['weekly','Отчет за неделю']],administration:[['admin_users','Пользователи'],['admin_backups','Резервные копии'],['admin_database','Проверка базы'],['references','Справочники'],['admin_audit','Журнал действий']],monitoring:[['monitoring','Состояние']],profile:[['profile','Личные данные']]};
let state={equipment:[],operations:[],categories:[],locations:[],stats:{},task_sources:[],task_types:[],work_log_statuses:[],references:[],reference_kinds:{},balance:[],recent_receipts:[],problems:{},problem_counts:{},searchRows:[],daily_report_uploads:[],current_user:{}};let currentSection='warehouse';
const byId=id=>document.getElementById(id);
const setText=(id,text)=>{const el=byId(id);if(el)el.textContent=text};
const htmlFragment=markup=>document.createRange().createContextualFragment(String(markup??''));
const setHtml=(id,markup)=>{const el=byId(id);if(el)el.replaceChildren(htmlFragment(markup))};
const replaceContent=(target,markup)=>{const el=resolveEl(target);if(el)el.replaceChildren(htmlFragment(markup));return el};
const resolveEl=target=>typeof target==='string'?byId(target):target;
const show=(target,display='')=>{const el=resolveEl(target);if(el){el.hidden=false;if(display!==undefined)el.style.display=display}return el};
const hide=target=>{const el=resolveEl(target);if(el)el.hidden=true;return el};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const option=(value,label=value)=>`<option value="${esc(value)}">${esc(label)}</option>`;
function notify(message,error=false){const x=byId('status');if(!x)return;setText('status',message);x.className='status show'+(error?' error':'');clearTimeout(x.timer);x.timer=setTimeout(()=>x.className='status',4000)}
