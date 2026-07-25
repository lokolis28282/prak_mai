/* Run against Chrome and a marker-guarded Stage 0.13.3A.5 pilot DB copy. */
const http=require('http');
const get=url=>new Promise((resolve,reject)=>http.get(url,response=>{let body='';response.on('data',chunk=>body+=chunk);response.on('end',()=>resolve(JSON.parse(body)))}).on('error',reject));
const sleep=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));

(async()=>{
  const smokeStarted=Date.now();
  const appUrl=process.argv[2],debugPort=process.argv[3],selectionId=Number(process.argv[4]);
  const expectedSerial=process.argv[5],expectedSourceName=process.argv[6],expectedCanonicalName=process.argv[7];
  const pages=await get(`http://127.0.0.1:${debugPort}/json`),page=pages.find(item=>item.type==='page'&&item.url.startsWith(appUrl));
  if(!page)throw Error('migration pilot page not found');
  const ws=new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
  let commandId=0;const pending=new Map(),runtimeExceptions=[],consoleErrors=[],logErrors=[],resourceErrors=[],httpErrors=[],api500=[];
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
    const id=++commandId,timer=setTimeout(()=>{pending.delete(id);reject(Error(`CDP timeout: ${method}`))},6000);
    pending.set(id,message=>{clearTimeout(timer);resolve(message)});ws.send(JSON.stringify({id,method,params}));
  });
  const evaluate=async expression=>{
    const message=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
    if(message.result?.exceptionDetails)throw Error(message.result.exceptionDetails.exception?.description||message.result.exceptionDetails.text);
    return message.result?.result?.value;
  };
  const waitFor=async expression=>{for(let attempt=0;attempt<80;attempt++){if(await evaluate(expression))return;await sleep(100)}throw Error(`Timeout: ${expression}`)};
  await send('Runtime.enable');await send('Log.enable');await send('Network.enable');await send('Page.enable');
  await send('Page.addScriptToEvaluateOnNewDocument',{source:`window.__pilotWindowErrorCount=0;window.__pilotUnhandledRejectionCount=0;window.addEventListener('error',()=>{window.__pilotWindowErrorCount+=1});window.addEventListener('unhandledrejection',()=>{window.__pilotUnhandledRejectionCount+=1});`});
  runtimeExceptions.length=0;consoleErrors.length=0;logErrors.length=0;resourceErrors.length=0;httpErrors.length=0;api500.length=0;
  await send('Page.reload',{ignoreCache:true});await sleep(250);
  await waitFor(`document.readyState==='complete'&&document.getElementById('login')!==null`);
  if(await evaluate(`document.getElementById('login')!==null`)){
    await evaluate(`document.querySelector('[name=full_name]').value='Пилот Ревью';document.getElementById('login').requestSubmit()`);
  }
  const listStarted=Date.now();
  try{
    await waitFor(`document.body.classList.contains('migration-pilot-active')&&document.getElementById('migration_pilot')?.classList.contains('active')&&document.querySelectorAll('#migrationPilotBody tr').length>0`);
  }catch(error){
    const diagnostic=await evaluate(`({url:location.href,login:!!document.getElementById('login'),loginError:document.getElementById('error')?.textContent||'',interfaceError:document.getElementById('interfaceError')?.textContent||'',pilotEnabled:window.state?.migration_pilot?.enabled||false,bodyClass:document.body.className,rows:document.querySelectorAll('#migrationPilotBody tr').length})`);
    throw Error(`${error.message}; state=${JSON.stringify(diagnostic)}; runtime=${JSON.stringify(runtimeExceptions)}; console=${JSON.stringify(consoleErrors)}; log=${JSON.stringify(logErrors)}; http=${JSON.stringify(httpErrors)}`);
  }
  const listOpenMs=Date.now()-listStarted;
  const banner=await evaluate(`document.querySelector('.migration-pilot-banner')?.textContent||''`);
  if(!banner.includes('МИГРАЦИОННЫЙ ПИЛОТ')||!banner.includes('warehouse_pilot_candidate.db'))throw Error(`pilot banner: ${banner}`);
  if(banner.includes('/Users/')||banner.includes('\\Users\\'))throw Error('absolute local path leaked into banner');
  const bannerVisible=await evaluate(`(()=>{const banner=document.querySelector('.migration-pilot-banner'),top=document.querySelector('.top'),b=banner?.getBoundingClientRect(),t=top?.getBoundingClientRect();return Boolean(b&&t&&b.width>0&&b.height>0&&t.top>=b.bottom-1)})()`);
  if(!bannerVisible)throw Error('pilot banner is hidden or covers the app header');
  const exactSearchStarted=Date.now();
  await evaluate(`(()=>{const input=document.getElementById('migrationPilotQuery');input.value=${JSON.stringify(expectedSerial)};document.getElementById('migrationPilotSearch').requestSubmit();return true})()`);
  await waitFor(`document.querySelector('#migrationPilotBody tr[data-decision="IMPORT"] code')?.textContent===${JSON.stringify(expectedSerial)}`);
  const exactSearchMs=Date.now()-exactSearchStarted;
  const rowContract=await evaluate(`(()=>{const row=document.querySelector('#migrationPilotBody tr[data-decision="IMPORT"]');return {serial:row.querySelector('code')?.textContent,source:row.textContent.includes(${JSON.stringify(expectedSourceName)}),canonical:row.textContent.includes(${JSON.stringify(expectedCanonicalName)}),button:Number(row.querySelector('button')?.dataset.pilotSelectionId||0)}})()`);
  if(rowContract.serial!==expectedSerial||!rowContract.source||!rowContract.canonical||rowContract.button!==selectionId)throw Error(`pilot row mismatch: ${JSON.stringify(rowContract)}`);
  const cardStarted=Date.now();
  await evaluate(`document.querySelector('#migrationPilotBody tr[data-decision="IMPORT"] button').click()`);
  await waitFor(`document.getElementById('positionModal').classList.contains('show')&&document.querySelector('.equipment-migration-section')`);
  const cardAndTimelineMs=Date.now()-cardStarted;
  const card=await evaluate(`(()=>({details:document.getElementById('positionDetails').textContent,history:document.getElementById('positionHistory').textContent,serial:[...document.querySelectorAll('#positionDetails .equipment-field')].find(node=>node.querySelector('dt')?.textContent==='S/N')?.querySelector('dd')?.textContent||'',assignment:!!document.querySelector('.equipment-inventory-assignment'),sourceRows:document.querySelectorAll('.equipment-migration-section tbody tr').length}))()`);
  if(card.serial!==expectedSerial)throw Error(`leading-zero S/N mismatch: ${JSON.stringify(card.serial)}`);
  if(!card.details.includes(expectedSourceName)||!card.details.includes(expectedCanonicalName)||!card.details.includes('Preservation Status'))throw Error('migration names/preservation missing from Equipment Card');
  if(!card.history.includes('Исторический приход (миграция)')||!card.history.includes('MIGRATION_RECEIPT_IMPORTED'))throw Error(`migration Timeline missing: ${card.history}`);
  if(card.assignment||card.sourceRows<1)throw Error('pilot card is writable or has no provenance');
  await evaluate(`closePositionCard()`);
  await evaluate(`document.getElementById('migrationPilotQuery').value=''`);
  const filterResults={};
  for(const filter of ['QUARANTINE','CONFLICT','CORRUPTED']){
    await evaluate(`(()=>{const button=[...document.querySelectorAll('#migrationPilotFilters button')].find(item=>item.dataset.filter===${JSON.stringify(filter)});if(!button)throw Error('filter missing: '+${JSON.stringify(filter)});button.click();return true})()`);
    await waitFor(`document.querySelector('#migrationPilotFilters button.active')?.dataset.filter===${JSON.stringify(filter)}&&document.querySelectorAll('#migrationPilotBody tr[data-filter-bucket=${JSON.stringify(filter)}]').length>0&&[...document.querySelectorAll('#migrationPilotBody tr[data-filter-bucket]')].every(row=>row.dataset.filterBucket===${JSON.stringify(filter)})`);
    filterResults[filter]=await evaluate(`document.getElementById('migrationPilotResultCount').textContent`);
  }
  const interfaceError=await evaluate(`document.getElementById('interfaceError')?.textContent||''`);
  const browserCounters=await evaluate(`({windowErrorCount:window.__pilotWindowErrorCount||0,unhandledRejectionCount:window.__pilotUnhandledRejectionCount||0})`);
  const result={
    pilot:true,selectionId,exactSerial:card.serial===expectedSerial,sourceAndCanonical:true,timeline:true,
    sourceRows:card.sourceRows,filters:filterResults,interfaceError,
    performanceMs:{listOpen:listOpenMs,exactSearch:exactSearchMs,cardAndTimeline:cardAndTimelineMs,total:Date.now()-smokeStarted},
    consoleErrorCount:consoleErrors.length,windowErrorCount:browserCounters.windowErrorCount,
    unhandledRejectionCount:browserCounters.unhandledRejectionCount,
    runtimeExceptionCount:runtimeExceptions.length,logErrorCount:logErrors.length,
    resourceErrorCount:resourceErrors.length,httpErrorCount:httpErrors.length,api500Count:api500.length
  };
  console.log(JSON.stringify(result));ws.close();
  if(interfaceError||consoleErrors.length||browserCounters.windowErrorCount||browserCounters.unhandledRejectionCount||runtimeExceptions.length||logErrors.length||resourceErrors.length||httpErrors.length||api500.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exit(1)});
