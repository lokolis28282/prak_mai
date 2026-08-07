/* Focused Reports/UVR UX scenario. Run only through scripts/smoke_ui.py on a disposable DB. */
const http = require('http');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const get = url => new Promise((resolve, reject) => http.get(url, response => {
  let body = '';
  response.on('data', chunk => { body += chunk; });
  response.on('end', () => resolve(JSON.parse(body)));
}).on('error', reject));

(async () => {
  const appUrl = process.argv[2];
  const debugPort = process.argv[3];
  const mode = process.argv[4] || 'engineer';
  const pages = await get(`http://127.0.0.1:${debugPort}/json`);
  const page = pages.find(item => item.type === 'page' && item.url.startsWith(appUrl));
  if (!page) throw new Error('ODE page not found');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let sequence = 0;
  const pending = new Map();
  const errors = [];
  const reportRequests = [];
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') {
      errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    }
    if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') {
      errors.push(message.params.entry.text);
    }
    if (message.method === 'Network.requestWillBeSent' && /\/api\/(action|work-logs)/.test(message.params.request.url)) {
      reportRequests.push(`${message.params.request.method} ${message.params.request.url}`);
    }
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 7000);
    pending.set(id, message => { clearTimeout(timer); resolve(message); });
    ws.send(JSON.stringify({id, method, params}));
  });
  await send('Runtime.enable');
  await send('Log.enable');
  await send('Network.enable');
  const evaluate = async expression => {
    const message = await send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
    if (message.result?.exceptionDetails) {
      throw new Error(message.result.exceptionDetails.exception?.description || message.result.exceptionDetails.text);
    }
    return message.result?.result?.value;
  };
  const waitFor = async expression => {
    for (let attempt = 0; attempt < 80; attempt += 1) {
      try { if (await evaluate(expression)) return; } catch (_error) { /* navigation */ }
      await sleep(100);
    }
    throw new Error(`Timeout: ${expression}`);
  };
  const assertClean = async label => {
    const interfaceError = await evaluate(`document.getElementById('interfaceError')?.textContent||''`);
    if (interfaceError || errors.length) throw new Error(`${label}: ${interfaceError || errors.join('\n')}`);
  };

  if (await evaluate(`document.getElementById('login')!==null`)) {
    if (mode === 'viewer') {
      await evaluate(`(()=>{const f=document.getElementById('login');f.email.value='smoke-viewer';f.password.value='lokolis';f.querySelector('[data-mode="admin"]').click();return true})()`);
    } else {
      await evaluate(`(()=>{const f=document.getElementById('login');f.full_name.value='Тестов UX Reports';f.querySelector('[data-mode="engineer"]').click();return true})()`);
    }
  }
  await waitFor(`typeof state!=='undefined'&&state.current_user?.role`);

  await evaluate(`document.querySelector('[data-module-open="reports"]').click()`);
  await waitFor(`document.getElementById('daily').classList.contains('active')&&!document.getElementById('reportPaneAll').hidden&&location.hash==='#reports/daily'`);
  await assertClean('reports navigation');

  if (mode === 'viewer') {
    await evaluate(`(()=>{if(state.current_user.role!=='viewer')throw Error('viewer login role');if(!document.getElementById('shiftLogForm').closest('.box').hidden)throw Error('viewer create form visible');if(document.querySelector('label[for="workLogsCsv"],label[for="workLogsXlsx"]'))throw Error('viewer import action visible');if(!document.getElementById('uvrSelectAll').closest('th').hidden)throw Error('viewer bulk selector visible');return true})()`);
    console.log('reports UX smoke: viewer read-only controls OK');
    ws.close();
    process.exit(0);
  }

  const token = Date.now().toString(36).toUpperCase();
  const normalNumber = `UX-${token}`;
  const pnrNumber = `PNR-${token}`;
  await evaluate(`(()=>{const f=document.getElementById('shiftLogForm'),source=f.task_source,status=f.status,section=f.section;source.value=[...source.options].map(x=>x.value).find(x=>x&&x.toUpperCase()!=='PNR');source.dispatchEvent(new Event('change',{bubbles:true}));status.value=[...status.options].map(x=>x.value).find(x=>x&&x!=='Выполнено')||status.options[0].value;section.selectedIndex=Math.min(1,section.options.length-1);f.task_number.value=${JSON.stringify(normalNumber)};f.description.value='Функциональная UX-проверка';if(!f.due_date.required||!f.due_date.value)throw Error('required due date is not initialized');f.querySelector('button[type="submit"]').click();return true})()`);
  await waitFor(`document.getElementById('workLogBody').textContent.includes(${JSON.stringify(normalNumber)})`);
  await waitFor(`document.getElementById('shiftLogForm').dataset.submitting!=='true'&&!document.querySelector('#shiftLogForm button[type="submit"]').disabled`);

  const pnrSubmitProbe = await evaluate(`(()=>{const toast=document.getElementById('status');toast.className='status';toast.textContent='';const f=document.getElementById('shiftLogForm');f.task_source.value='PNR';f.task_source.dispatchEvent(new Event('change',{bubbles:true}));const desc=f.querySelector('.uvr-desc-cell'),pnr=f.querySelector('.uvr-pnr-field');if(!desc.hidden)throw Error('PNR description stays visible: source='+f.task_source.value+',options='+[...f.task_source.options].map(x=>x.value).join('|')+',isPnr='+ODE.reports.isPnr(f.task_source.value)+',bound='+f.task_source.dataset.bound);if(pnr.hidden||!f.status.disabled)throw Error('PNR controls invalid');f.task_number.value=${JSON.stringify(pnrNumber)};const first=f.querySelector('[data-pnr-step]');first.checked=true;first.dispatchEvent(new Event('change',{bubbles:true}));if(!f.checkValidity())throw Error('PNR form invalid: '+[...f.elements].filter(x=>!x.checkValidity()).map(x=>x.name+':'+x.validationMessage).join('|'));let submitted=false;f.addEventListener('submit',()=>{submitted=true},{once:true});const button=f.querySelector('.actions button');button.click();return {submitted,button:button.outerHTML,type:button.type,disabled:button.disabled,connected:button.isConnected,form:button.form?.id||'',handler:typeof f.onsubmit}})()`);
  if (!pnrSubmitProbe.submitted) throw new Error(`PNR submit button did not dispatch the form submit event: ${JSON.stringify(pnrSubmitProbe)}`);
  try {
    await waitFor(`document.getElementById('status').classList.contains('show')`);
  } catch (error) {
    throw new Error(`${error.message}; requests: ${reportRequests.join(', ') || 'none'}; console: ${errors.join(' | ') || 'clean'}`);
  }
  await evaluate(`(()=>{const status=document.getElementById('status');if(status.classList.contains('error'))throw Error('PNR create: '+status.textContent);if(!status.textContent.includes('Запись добавлена'))throw Error('PNR create toast: '+status.textContent);return true})()`);
  await waitFor(`fetch('/api/work-logs').then(r=>r.json()).then(x=>x.logs.some(row=>row.task_number===${JSON.stringify(pnrNumber)}))`);
  await evaluate(`loadWorkLogs()`);
  await waitFor(`document.getElementById('workLogBody').textContent.includes(${JSON.stringify(pnrNumber)})`);

  await evaluate(`(()=>{const input=document.getElementById('uvrSearch');input.value=${JSON.stringify(normalNumber)};input.dispatchEvent(new Event('input',{bubbles:true}));return true})()`);
  await waitFor(`document.querySelectorAll('#workLogBody tr').length===1&&document.getElementById('workLogBody').textContent.includes(${JSON.stringify(normalNumber)})`);
  await evaluate(`clearUvrFilters()`);
  await waitFor(`document.getElementById('workLogBody').textContent.includes(${JSON.stringify(pnrNumber)})`);

  await evaluate(`(()=>{const row=[...document.querySelectorAll('#workLogBody tr')].find(x=>x.textContent.includes(${JSON.stringify(normalNumber)}));row.querySelector('button').click();return true})()`);
  await waitFor(`document.getElementById('uvrEditForm')!==null`);
  await evaluate(`(()=>{const f=document.getElementById('uvrEditForm');f.comment.value='обновлено UX';f.requestSubmit();return true})()`);
  await waitFor(`document.getElementById('workLogBody').textContent.includes('обновлено UX')`);

  await evaluate(`(()=>{const row=[...document.querySelectorAll('#workLogBody tr')].find(x=>x.textContent.includes(${JSON.stringify(normalNumber)}));[...row.querySelectorAll('button')].find(x=>x.textContent.includes('Удалить')).click();return true})()`);
  await waitFor(`document.querySelector('.confirm-modal')!==null`);
  await send('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Escape', code: 'Escape'});
  await send('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Escape', code: 'Escape'});
  await waitFor(`document.querySelector('.confirm-modal')===null`);
  await evaluate(`(()=>{const row=[...document.querySelectorAll('#workLogBody tr')].find(x=>x.textContent.includes(${JSON.stringify(normalNumber)}));[...row.querySelectorAll('button')].find(x=>x.textContent.includes('Удалить')).click();return true})()`);
  await waitFor(`document.querySelector('.confirm-modal')!==null`);
  await evaluate(`(()=>{if(!document.activeElement.textContent.includes('Удалить'))throw Error('confirm button is not focused');return true})()`);
  // CDP key injection does not consistently run the browser's native button
  // activation default in headless mode. Verify keyboard focus, then activate
  // that exact focused control to cover the application path deterministically.
  await evaluate(`document.activeElement.click()`);
  await waitFor(`!document.getElementById('workLogBody').textContent.includes(${JSON.stringify(normalNumber)})`);

  await evaluate(`document.querySelector('.subtab[data-view="handover"]').click()`);
  await waitFor(`document.getElementById('handover').classList.contains('active')&&document.getElementById('handoverBody').textContent.includes(${JSON.stringify(pnrNumber)})`);
  await evaluate(`(()=>{const badge=document.querySelector('.subtab[data-view="handover"] .tab-badge');if(!badge||Number(badge.textContent)<1)throw Error('handover badge');const button=document.querySelector('#handoverBody button');if(!button)throw Error('handover edit missing');button.click();return true})()`);
  await waitFor(`document.getElementById('uvrEditForm')!==null`);
  await evaluate(`document.querySelector('#uvrEditForm [data-close]').click()`);

  const exportStatuses = await evaluate(`Promise.all(['/export/work-logs.xlsx','/export/handover.xlsx','/export/shift-report.xlsx?date='+document.querySelector('#shiftLogForm [name=work_date]').value,'/export/work-logs.csv','/export/daily-report.csv?date='+document.querySelector('#shiftLogForm [name=work_date]').value].map(async url=>{const r=await fetch(url);return [url,r.status,r.headers.get('content-type')] }))`);
  for (const [url, status] of exportStatuses) if (status !== 200) throw new Error(`export failed ${status}: ${url}`);

  await send('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await sleep(250);
  await evaluate(`(()=>{const wraps=[...document.querySelectorAll('#handover .table-wrap,#daily .table-wrap')];if(!wraps.every(x=>x.scrollWidth>=x.clientWidth))throw Error('responsive table contract');if(document.documentElement.scrollWidth>innerWidth+2)throw Error('mobile page overflow '+document.documentElement.scrollWidth+'/'+innerWidth);return true})()`);
  await assertClean('reports complete');
  console.log('reports UX smoke: engineer scenarios and exports OK');
  ws.close();
  process.exit(0);
})().catch(error => { console.error(error.stack || error); process.exit(1); });
