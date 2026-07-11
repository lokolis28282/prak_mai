async function request(url,options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw new Error(data.error||'Ошибка запроса');return data}
