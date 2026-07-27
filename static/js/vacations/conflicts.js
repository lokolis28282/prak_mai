(function(){
  const V=window.ODE.vacations;

  V.conflictCard=(requestId,items)=>{
    const first=items[0];
    const comment=renderElement('textarea',{
      className:'vacation-resolution-comment',
      attrs:{
        rows:'2',maxlength:'2000',
        placeholder:'Комментарий к решению (необязательно)',
        'aria-label':`Комментарий к решению по отпуску ${first.full_name}`
      }
    });
    const details=items.map(item=>renderElement('li',{children:[
      renderElement('strong',{text:V.conflictCodeLabels[item.code]||item.code}),
      renderElement('span',{text:item.details})
    ]}));
    return renderElement('article',{className:'vacation-conflict-card',children:[
      renderElement('div',{className:'vacation-conflict-head',children:[
        renderElement('div',{children:[
          renderElement('h3',{text:first.full_name}),
          renderElement('p',{text:
            `${V.dateText(first.date_from)} — ${V.dateText(first.date_to)} · ${first.calendar_days} календ. дн.`
          })
        ]}),
        V.badge('Ожидает решения','conflict')
      ]}),
      renderElement('ul',{className:'vacation-conflict-list',children:details}),
      comment,
      renderElement('div',{className:'vacation-conflict-actions',children:[
        renderButton({
          text:'Подтвердить исключение',className:'button primary',
          onClick:()=>V.resolveConflict(requestId,'APPROVED',comment.value)
        }),
        renderButton({
          text:'Отклонить отпуск',className:'button danger',
          onClick:()=>V.resolveConflict(requestId,'REJECTED',comment.value)
        })
      ]})
    ]});
  };

  V.resolveConflict=async(requestId,decision,comment='')=>{
    try{
      await request(`${V.api}/conflicts/${requestId}/resolve`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({decision,comment})
      });
      notify(decision==='APPROVED'?'Исключение подтверждено':'Отпуск отклонен');
      await V.load(true);
    }catch(error){
      notify(error.message,true);
    }
  };

  V.renderConflicts=root=>{
    const groups=new Map();
    for(const item of V.state.data.conflicts||[]){
      const id=Number(item.request_id);
      if(!groups.has(id))groups.set(id,[]);
      groups.get(id).push(item);
    }
    root.replaceChildren(
      V.pageHead(
        'Конфликты',
        'Здесь собраны отпуска, которые нарушают покрытие смен, пересекаются у руководителей или требуют одного подменного.'
      ),
      groups.size
        ?renderElement('div',{
          className:'vacation-conflict-grid',
          children:[...groups.entries()].map(([id,items])=>V.conflictCard(id,items))
        })
        :renderElement('div',{className:'vacation-empty',children:[
          renderElement('h3',{text:'Конфликтов нет'}),
          renderElement('p',{text:'Все внесённые отпуска проходят текущие правила планирования.'})
        ]})
    );
  };
})();
