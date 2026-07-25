/* Chrome/CDP smoke for product navigation plus the admin-only migration review. */
const http=require('http');
const get=url=>new Promise((resolve,reject)=>http.get(url,response=>{let body='';response.on('data',chunk=>body+=chunk);response.on('end',()=>resolve(JSON.parse(body)))}).on('error',reject));
const sleep=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));

(async()=>{
  const started=Date.now(),appUrl=process.argv[2],debugPort=process.argv[3],samples=JSON.parse(process.argv[4]);
  const pages=await get(`http://127.0.0.1:${debugPort}/json`),page=pages.find(item=>item.type==='page'&&item.url.startsWith(appUrl));
  if(!page)throw Error('full candidate page not found');
  const ws=new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
  let commandId=0;
  const pending=new Map(),runtimeExceptions=[],consoleErrors=[],logErrors=[],resourceErrors=[],httpErrors=[],api500=[];
  ws.onmessage=event=>{
    const message=JSON.parse(event.data);
    if(message.method==='Runtime.exceptionThrown')runtimeExceptions.push(message.params.exceptionDetails.exception?.description||message.params.exceptionDetails.text);
    if(message.method==='Runtime.consoleAPICalled'&&message.params.type==='error')consoleErrors.push(message.params.args?.map(item=>item.value||item.description||'').join(' ')||'console.error');
    if(message.method==='Log.entryAdded'&&message.params.entry.level==='error')logErrors.push(message.params.entry.text);
    if(message.method==='Network.loadingFailed')resourceErrors.push(`${message.params.type}: ${message.params.errorText}`);
    if(message.method==='Network.responseReceived'&&message.params.response.status>=400){
      httpErrors.push(`${message.params.response.status}: ${message.params.response.url}`);
      if(message.params.response.status>=500)api500.push(`${message.params.response.status}: ${message.params.response.url}`);
    }
    if(message.id&&pending.has(message.id)){pending.get(message.id)(message);pending.delete(message.id)}
  };
  const send=(method,params={})=>new Promise((resolve,reject)=>{
    const id=++commandId,timer=setTimeout(()=>{pending.delete(id);reject(Error(`CDP timeout: ${method}`))},10000);
    pending.set(id,message=>{clearTimeout(timer);resolve(message)});ws.send(JSON.stringify({id,method,params}));
  });
  const evaluate=async expression=>{
    const message=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
    if(message.result?.exceptionDetails)throw Error(message.result.exceptionDetails.exception?.description||message.result.exceptionDetails.text);
    return message.result?.result?.value;
  };
  const waitFor=async(expression,attempts=180)=>{for(let attempt=0;attempt<attempts;attempt++){if(await evaluate(expression))return;await sleep(100)}throw Error(`Timeout: ${expression}`)};
  const clickPrimary=label=>evaluate(`(()=>{const button=[...document.querySelectorAll('.primary-nav .section-button')].find(item=>item.textContent===${JSON.stringify(label)});if(!button)throw Error('primary navigation missing: '+${JSON.stringify(label)});button.click();return true})()`);
  const technicalWords=['TEXT_EXACT','NUMERIC_PROVISIONAL','SOURCE_CORRUPTED','CONFLICT','OPENING_STATE','Migration','Candidate','Source row','Raw XML','Review status'];

  await send('Runtime.enable');await send('Log.enable');await send('Network.enable');await send('Page.enable');
  await send('Page.addScriptToEvaluateOnNewDocument',{source:`window.__fullWindowErrorCount=0;window.__fullUnhandledRejectionCount=0;window.addEventListener('error',()=>window.__fullWindowErrorCount++);window.addEventListener('unhandledrejection',()=>window.__fullUnhandledRejectionCount++);`});
  await send('Page.reload',{ignoreCache:true});await sleep(250);
  await waitFor(`document.readyState==='complete'&&document.getElementById('login')!==null`);
  await evaluate(`document.querySelector('[name=full_name]').value='Инженер Ручной Проверки';document.getElementById('login').requestSubmit()`);
  await waitFor(`document.body.classList.contains('migration-full-active')&&document.querySelector('.primary-nav')&&document.getElementById('home')?.classList.contains('active')`,240);

  const banner=await evaluate(`document.querySelector('.migration-full-banner')?.textContent||''`);
  if(!banner.includes('ПОЛНАЯ КАНДИДАТНАЯ БАЗА СКЛАДА'))throw Error(`full banner: ${banner}`);
  if(banner.includes('/Users/')||banner.includes('\\Users\\'))throw Error('absolute local path leaked into banner');
  const bannerGeometry=await evaluate(`(()=>{const banner=document.querySelector('.migration-full-banner'),top=document.querySelector('.top'),b=banner?.getBoundingClientRect(),t=top?.getBoundingClientRect();return {visible:Boolean(b&&t&&b.width>0&&b.height>0&&t.top>=b.bottom-1),banner:b?{bottom:b.bottom,height:b.height}:null,header:t?{top:t.top,height:t.height}:null}})()`);
  if(!bannerGeometry.visible)throw Error(`service strip covers application header: ${JSON.stringify(bannerGeometry)}`);

  const engineerShell=await evaluate(`(()=>({labels:[...document.querySelectorAll('.primary-nav .section-button')].map(item=>item.textContent),adminHidden:document.querySelector('[data-section="administration"]')?.hidden,migrationRoot:!!document.getElementById('migration_pilot'),home:document.getElementById('home')?.textContent||''}))()`);
  const expectedNavigation=['ODE','Мониторинг','Работы','Склад','Отчеты','Администрирование'];
  if(JSON.stringify(engineerShell.labels)!==JSON.stringify(expectedNavigation)||!engineerShell.adminHidden||engineerShell.migrationRoot)throw Error(`engineer shell contract failed: ${JSON.stringify(engineerShell)}`);

  const warehouseStarted=Date.now();
  await clickPrimary('Склад');
  await waitFor(`document.getElementById('balance')?.classList.contains('active')`);
  const warehouseContract=await evaluate(`({summary:document.querySelectorAll('#balanceSummary .card').length,filters:document.querySelectorAll('#balance .filters select').length,subtabs:[...document.querySelectorAll('#subnav .subtab')].map(item=>item.textContent)})`);
  if(warehouseContract.summary!==4||warehouseContract.filters<5)throw Error(`warehouse workspace controls missing: ${JSON.stringify(warehouseContract)}`);
  const warehouseText=await evaluate(`document.querySelector('main.main')?.textContent||''`);
  for(const word of technicalWords)if(warehouseText.includes(word))throw Error(`technical term leaked into engineer workspace: ${word}`);
  if(/миграци/i.test(warehouseText))throw Error(`migration wording leaked into engineer workspace: ${JSON.stringify(warehouseText.match(/.{0,80}миграци.{0,80}/gi)?.slice(0,5))}`);
  const warehouseOpenMs=Date.now()-warehouseStarted;

  const cardStarted=Date.now(),serial=samples.leading.display_serial_value;
  await evaluate(`(()=>{const input=document.getElementById('balanceQuery');input.value=${JSON.stringify(serial)};input.dispatchEvent(new Event('input',{bubbles:true}));return true})()`);
  await waitFor(`document.getElementById('balanceBody')?.textContent.includes(${JSON.stringify(serial)})&&document.querySelector('#balanceBody button')`);
  await evaluate(`document.querySelector('#balanceBody button').click()`);
  await waitFor(`document.getElementById('positionModal')?.classList.contains('show')&&document.getElementById('positionDetails')?.textContent.includes(${JSON.stringify(samples.leading.canonical_item_name)})`,240);
  const engineerCard=await evaluate(`(()=>({details:document.getElementById('positionDetails').textContent,history:document.getElementById('positionHistory').textContent,technical:!!document.querySelector('.equipment-migration-section'),future:document.querySelectorAll('.equipment-product-section.future').length,receipts:document.querySelector('.equipment-history-summaries')?.textContent||''}))()`);
  if(!engineerCard.details.includes(samples.leading.source_item_name)||!engineerCard.details.includes(samples.leading.canonical_item_name)||engineerCard.technical||engineerCard.future!==4||!engineerCard.receipts.includes('История приходов'))throw Error(`normal equipment card contract failed: ${JSON.stringify(engineerCard)}`);
  for(const word of technicalWords)if(`${engineerCard.details} ${engineerCard.history}`.includes(word))throw Error(`technical term leaked into equipment card: ${word}`);
  if(/миграци/i.test(`${engineerCard.details} ${engineerCard.history}`))throw Error('migration wording leaked into equipment card');
  const cardOpenMs=Date.now()-cardStarted;
  await evaluate(`closePositionCard();logout()`);
  await waitFor(`document.getElementById('login')!==null`);

  await evaluate(`document.getElementById('mode').click();document.querySelector('[name=email]').value='lokolis';document.querySelector('[name=password]').value='lokolis';document.getElementById('login').requestSubmit()`);
  await waitFor(`document.querySelector('.primary-nav')&&document.querySelector('[data-section="administration"]')?.hidden===false`,240);
  await clickPrimary('Администрирование');
  await waitFor(`[...document.querySelectorAll('#subnav .subtab')].some(item=>item.textContent==='Миграция данных')`);
  await evaluate(`[...document.querySelectorAll('#subnav .subtab')].find(item=>item.textContent==='Миграция данных').click()`);
  const adminReviewStarted=Date.now();
  await waitFor(`document.getElementById('migration_pilot')?.classList.contains('active')&&document.querySelectorAll('#migrationPilotCounts .card').length===12&&document.querySelectorAll('#migrationPilotBody tr').length>0`,240);
  const adminNavigation=await evaluate(`(()=>({standalone:!!document.getElementById('migrationPilotNavigation'),adminActive:document.querySelector('.primary-nav .section-button.active')?.textContent,subtab:document.querySelector('#subnav .subtab.active')?.textContent}))()`);
  if(adminNavigation.standalone||adminNavigation.adminActive!=='Администрирование'||adminNavigation.subtab!=='Миграция данных')throw Error(`admin route contract failed: ${JSON.stringify(adminNavigation)}`);
  const adminReviewOpenMs=Date.now()-adminReviewStarted;

  const numeric=samples.numeric;
  await evaluate(`(()=>{document.getElementById('migrationPilotQuery').value=${JSON.stringify(numeric.display_serial_value)};const button=[...document.querySelectorAll('#migrationPilotFilters button')].find(item=>item.dataset.filter==='NUMERIC_PROVISIONAL');button.click();return true})()`);
  await waitFor(`document.querySelector('#migrationPilotBody tr[data-decision="NUMERIC_PROVISIONAL_IMPORTED"]')?.textContent.includes(${JSON.stringify(numeric.raw_xml_value)})`);
  await evaluate(`document.querySelector('#migrationPilotBody tr[data-decision="NUMERIC_PROVISIONAL_IMPORTED"] button').click()`);
  await waitFor(`document.getElementById('positionModal')?.classList.contains('show')&&document.querySelector('.equipment-migration-section')?.textContent.includes('Raw XML Token')`);
  const adminCard=await evaluate(`document.getElementById('positionDetails').textContent`);
  if(!adminCard.includes(numeric.raw_xml_value)||!adminCard.includes('Preservation Status'))throw Error('administrator review details are incomplete');

  const interfaceError=await evaluate(`document.getElementById('interfaceError')?.textContent||''`);
  const counters=await evaluate(`({windowErrorCount:window.__fullWindowErrorCount||0,unhandledRejectionCount:window.__fullUnhandledRejectionCount||0})`);
  const result={
    productNavigation:true,engineerMigrationHidden:true,warehouseWorkspace:true,unifiedEquipmentCard:true,adminMigrationRoute:true,
    performanceMs:{warehouseOpen:warehouseOpenMs,cardOpen:cardOpenMs,adminReviewOpen:adminReviewOpenMs,total:Date.now()-started},
    interfaceError,consoleErrorCount:consoleErrors.length,windowErrorCount:counters.windowErrorCount,
    unhandledRejectionCount:counters.unhandledRejectionCount,runtimeExceptionCount:runtimeExceptions.length,
    logErrorCount:logErrors.length,resourceErrorCount:resourceErrors.length,httpErrorCount:httpErrors.length,api500Count:api500.length
  };
  console.log(JSON.stringify(result));ws.close();
  if(interfaceError||consoleErrors.length||counters.windowErrorCount||counters.unhandledRejectionCount||runtimeExceptions.length||logErrors.length||resourceErrors.length||httpErrors.length||api500.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exit(1)});
