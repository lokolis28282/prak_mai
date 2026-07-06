/* Run against Chrome --remote-debugging-port=9223 and a disposable ODE database. */
const http = require('http');
const get = url => new Promise((resolve, reject) => http.get(url, r => {
  let body = ''; r.on('data', c => body += c); r.on('end', () => resolve(JSON.parse(body)));
}).on('error', reject));
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const appUrl=process.argv[2]||'http://127.0.0.1:8876',debugPort=process.argv[3]||'9223';
  const pages = await get(`http://127.0.0.1:${debugPort}/json`);
  const page = pages.find(x => x.type === 'page' && x.url.startsWith(appUrl));
  if (!page) throw new Error('ODE page not found');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let id = 0; const pending = new Map();
  ws.onmessage = event => { const m = JSON.parse(event.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
  const send = (method, params = {}) => new Promise((resolve,reject) => { const n = ++id,t=setTimeout(()=>{pending.delete(n);reject(Error(`CDP timeout: ${method}`))},5000);pending.set(n,m=>{clearTimeout(t);resolve(m)});ws.send(JSON.stringify({id:n, method, params})); });
  const evaluate = async expression => {
    const m = await send('Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true});
    if (m.result?.exceptionDetails) throw new Error(m.result.exceptionDetails.exception?.description||m.result.exceptionDetails.text);
    return m.result?.result?.value;
  };
  const waitFor = async expression => { for (let i=0;i<50;i++) { if (await evaluate(expression)) return; await sleep(100); } throw new Error(`Timeout: ${expression}`); };
  if (await evaluate(`document.getElementById('login')!==null`)) await evaluate(`document.querySelector('[name=full_name]').value='Тестов Инженер Смены';document.getElementById('login').requestSubmit()`);
  await waitFor(`document.querySelector('.home-screen.active')!==null`);
  const clickText = text => evaluate(`(()=>{const active=document.querySelector('.view.active');const x=[...document.querySelectorAll('button')].find(x=>x.textContent.includes(${JSON.stringify(text)})&&!x.hidden&&(active?.contains(x)||x.closest('.top')||x.closest('.subnav')));if(!x)throw Error('active button: '+${JSON.stringify(text)});x.click();return true})()`);
  const clickCard = title => evaluate(`(()=>{const card=[...document.querySelectorAll('.portal-card')].find(x=>x.querySelector('h3')?.textContent===${JSON.stringify(title)});if(!card)throw Error('card: '+${JSON.stringify(title)});card.querySelector('button').click()})()`);
  const assertClean = async label => { const value=await evaluate(`document.getElementById('interfaceError')?.textContent||''`); if(value)throw Error(`${label}: ${value}`); };
  await clickCard('Склад'); await clickText('Принять оборудование'); await clickText('Сканировать оборудование');
  for (const text of ['Оборудование','Сервер','Dell','PowerEdge R650']) await clickText(text);
  await evaluate(`if(wShelf.options.length<2)wShelf.add(new Option('A-01','A-01'));if(wDc.options.length<2)wDc.add(new Option('Ixcellerate','Ixcellerate'));wShelf.selectedIndex=1;wDc.selectedIndex=1;document.querySelector('.wizard-next').click()`);
  try { await waitFor(`document.getElementById('receiptScanner')&&!document.getElementById('receiptScanner').closest('.scanner-box').hidden&&document.getElementById('receipt').classList.contains('active')`); }
  catch (error) { throw new Error(error.message+' '+JSON.stringify(await evaluate(`({heading:document.querySelector('.wizard-shell h2')?.textContent,status:status?.textContent,uiError:interfaceError?.textContent,form:!!document.getElementById('scanReceiptForm'),scanner:!!document.getElementById('receiptScanner'),scannerHidden:document.getElementById('receiptScanner')?.closest('.scanner-box').hidden,receiptClass:document.getElementById('receipt')?.className,stageHidden:document.querySelector('#receipt .scenario-stage')?.hidden,stage:document.querySelector('#receipt .scenario-stage')?.innerText})`))); }
  for (const sn of ['ODE012-SMOKE-A','ODE012-SMOKE-B']) {
    await evaluate(`receiptScanner.value=${JSON.stringify(sn)};receiptScanner.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))`); await sleep(250);
  }
  await waitFor(`document.querySelectorAll('#scanReceiptBody tr').length===2&&document.getElementById('activeDrafts')&&!document.getElementById('activeDrafts').hidden`);
  await clickText('ODE');
  await evaluate(`document.querySelector('#activeDrafts button').click()`);
  await waitFor(`document.getElementById('receipt').classList.contains('active')&&document.querySelectorAll('#scanReceiptBody tr').length===2`);
  await evaluate(`document.querySelector('#scanReceiptBody button').click()`);
  await waitFor(`document.querySelectorAll('#scanReceiptBody tr').length===1`);
  await evaluate(`document.getElementById('confirmScanReceipts').click()`); await sleep(500);
  await assertClean('receipt'); await clickText('Расход'); await assertClean('issue'); await clickText('Баланс'); await assertClean('balance');
  await waitFor(`document.querySelectorAll('#balanceKpis .kpi-card').length===6`);
  await evaluate(`document.querySelector('#balanceKpis .kpi-card').click()`);
  await waitFor(`document.querySelector('#balanceKpis .kpi-card.active')!==null`);
  await clickText('История'); await waitFor(`document.querySelectorAll('#operationBody tr').length>0`); await assertClean('history'); await clickText('Профиль'); await assertClean('profile'); await clickText('Обновить'); await sleep(300); await assertClean('refresh');
  await clickText('ODE');
  await clickCard('Отчеты'); await waitFor(`document.getElementById('daily').classList.contains('active')`); await assertClean('reports'); await clickText('ODE');
  await clickCard('Мониторинг'); await waitFor(`document.getElementById('monitoring').classList.contains('active')`); await assertClean('monitoring'); await clickText('ODE');
  await clickCard('Профиль'); await waitFor(`document.getElementById('profile').classList.contains('active')`); await assertClean('profile card'); await clickText('ODE');
  await clickCard('Склад'); await clickText('Поставки'); await assertClean('deliveries'); await clickText('Инвентаризация'); await assertClean('inventory'); await clickText('ODE');
  const result = await evaluate(`({home:document.querySelector('#home.active')!==null,errors:document.getElementById('interfaceError')?.textContent||'',receiptSaved:state.recent_receipts.some(x=>x.serial_number==='ODE012-SMOKE-B'),balanceCards:document.querySelectorAll('#balanceKpis .kpi-card').length})`);
  console.log(JSON.stringify(result)); ws.close();
  if (!result.home || result.errors || !result.receiptSaved || result.balanceCards!==6) process.exitCode = 1;
})().catch(e => { console.error(e); process.exit(1); });
