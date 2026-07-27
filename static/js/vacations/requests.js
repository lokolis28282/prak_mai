(function(){
  const V=window.ODE.vacations;

  V.requestForm=()=>{
    const data=V.state.data;
    const existing=V.state.editRequestId
      ?(data.requests||[]).find(item=>Number(item.id)===Number(V.state.editRequestId))
      :null;
    const employee=renderSelect({
      name:'employee_id',required:true,value:String(existing?.employee_id||''),
      options:[['','Выберите сотрудника'],...(data.employees||[]).map(item=>[
        String(item.id),`${item.full_name} · ${item.site_label} · ${item.schedule_label}`
      ])]
    });
    const start=renderElement('input',{attrs:{
      name:'date_from',type:'date',required:true,value:existing?.date_from||''
    }});
    const end=renderElement('input',{attrs:{
      name:'date_to',type:'date',required:true,value:existing?.date_to||''
    }});
    const status=renderSelect({
      name:'sfera_status',value:existing?.sfera_status||'PLANNED',
      options:V.optionRows(data.options.sfera_statuses)
    });
    const substitute=renderSelect({
      name:'substitute_employee_id',value:String(existing?.substitute_employee_id||''),
      options:[['','Без подменного'],...(data.employees||[])
        .filter(item=>item.is_substitute)
        .map(item=>[String(item.id),item.full_name])]
    });
    const reference=renderElement('input',{attrs:{
      name:'sfera_reference',maxlength:'500',value:existing?.sfera_reference||'',
      placeholder:'Номер заявки или ссылка'
    }});
    const comment=renderElement('textarea',{attrs:{
      name:'comment',maxlength:'2000',rows:'3',
      placeholder:'Комментарий для планирования'
    },text:existing?.comment||''});
    const errorBox=renderElement('div',{className:'vacation-form-error',attrs:{role:'alert'}});
    const save=renderButton({
      text:existing?'Сохранить изменения':'Добавить отпуск',
      className:'button primary',type:'submit'
    });
    const form=renderElement('form',{className:'vacation-form',children:[
      V.field('Сотрудник',employee,true),V.field('Начало',start),V.field('Окончание',end),
      V.field('Статус в Сфере',status),V.field('Подменный',substitute),
      V.field('Заявка в Сфере',reference,true),V.field('Комментарий',comment,true),
      errorBox,
      renderElement('div',{className:'vacation-form-actions',children:[
        save,
        existing?renderButton({
          text:'Отмена',className:'button',
          onClick:()=>{
            V.state.editRequestId=null;
            V.renderRequests(byId('vacations_list'));
          }
        }):null
      ]})
    ],on:{submit:async event=>{
      event.preventDefault();errorBox.textContent='';save.disabled=true;
      const payload=Object.fromEntries(new FormData(form).entries());
      payload.employee_id=Number(payload.employee_id);
      payload.substitute_employee_id=payload.substitute_employee_id
        ?Number(payload.substitute_employee_id):null;
      try{
        const endpoint=existing
          ?`${V.api}/requests/${existing.id}/update`
          :`${V.api}/requests`;
        const response=await request(endpoint,{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(payload)
        });
        V.state.editRequestId=null;
        const pending=response.request?.conflict_status==='PENDING';
        notify(
          pending?'Отпуск сохранен и отправлен в «Конфликты»':'Отпуск сохранен',
          pending
        );
        await V.load(true);
      }catch(error){
        errorBox.textContent=error.message;
      }finally{
        save.disabled=false;
      }
    }}});
    return form;
  };

  V.requestRow=item=>{
    const statusKind=item.sfera_status==='APPROVED'
      ?'approved'
      :item.sfera_status==='REJECTED'||item.sfera_status==='CANCELLED'?'rejected':'';
    const conflictKind=item.conflict_status==='PENDING'
      ?'conflict'
      :item.conflict_status==='APPROVED_EXCEPTION'
        ?'approved'
        :item.conflict_status==='REJECTED'?'rejected':'';
    return renderElement('tr',{children:[
      renderElement('td',{children:[
        renderElement('strong',{text:item.full_name}),
        renderElement('small',{text:
          `${item.site_label||V.siteLabel(item.site)} · ${V.scheduleLabel(item.schedule_type)}`
        })
      ]}),
      renderElement('td',{text:V.periodText(item)}),
      renderElement('td',{children:[
        V.badge(V.statusLabels[item.sfera_status]||item.sfera_status,statusKind)
      ]}),
      renderElement('td',{text:item.substitute_name||'—'}),
      renderElement('td',{children:[
        V.badge(
          V.conflictLabels[item.conflict_status]||item.conflict_status,
          conflictKind
        )
      ]}),
      renderElement('td',{children:[
        renderButton({text:'Изменить',className:'button',onClick:()=>{
          V.state.editRequestId=Number(item.id);
          V.renderRequests(byId('vacations_list'));
          window.scrollTo({top:0,behavior:'smooth'});
        }})
      ]})
    ]});
  };

  V.renderRequests=root=>{
    const rows=V.state.data.requests||[];
    root.replaceChildren(
      V.pageHead(
        'Список отпусков',
        'Вносите сюда ручные изменения после планирования и согласования в Сфере. Дни считаются календарными.'
      ),
      renderElement('section',{className:'vacation-form-card',children:[
        renderElement('h3',{text:V.state.editRequestId?'Изменить отпуск':'Новый отпуск'}),
        V.requestForm()
      ]}),
      renderElement('div',{className:'table-wrap vacation-table',children:[
        renderElement('table',{children:[
          renderElement('thead',{children:[
            renderElement('tr',{children:
              ['Сотрудник','Период','Сфера','Подменный','Проверка','']
                .map(text=>renderElement('th',{text}))
            })
          ]}),
          renderElement('tbody',{children:rows.length?rows.map(V.requestRow):[
            renderElement('tr',{children:[
              renderElement('td',{
                className:'empty',attrs:{colspan:6},
                text:'Отпусков в выбранном периоде пока нет'
              })
            ]})
          ]})
        ]})
      ]})
    );
  };
})();
