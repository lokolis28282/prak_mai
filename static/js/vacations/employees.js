(function(){
  const V=window.ODE.vacations;

  const shiftSummary=employees=>{
    const groups=[0,1,2,3].map(group=>{
      const names=employees
        .filter(item=>item.schedule_type==='ONE_THREE'&&Number(item.shift_group)===group)
        .map(item=>item.last_name)
        .join(' и ');
      return `смена ${group+1} — ${names||'не назначена'}`;
    });
    return `Цикл 1/3: ${groups.join('; ')}. Отсчёт начинается 26.07.2026.`;
  };

  V.assignmentEditor=employee=>{
    const data=V.state.data;
    const site=renderSelect({
      name:'site',value:employee.site,options:V.optionRows(data.options.sites)
    });
    const schedule=renderSelect({
      name:'schedule_type',value:employee.schedule_type,
      options:V.optionRows(data.options.schedules)
    });
    const group=renderSelect({
      name:'shift_group',value:employee.shift_group===null?'':String(employee.shift_group),
      options:[
        ['','Не применяется'],['0','Смена 1'],['1','Смена 2'],
        ['2','Смена 3'],['3','Смена 4']
      ]
    });
    const validFrom=renderElement('input',{attrs:{
      name:'valid_from',type:'date',required:true,value:V.isoLocal(new Date())
    }});
    const note=renderElement('input',{attrs:{
      name:'note',maxlength:'1000',placeholder:'Причина изменения'
    }});
    const errorBox=renderElement('div',{className:'vacation-form-error',attrs:{role:'alert'}});
    const form=renderElement('form',{className:'vacation-assignment-form',children:[
      V.field('Площадка',site),V.field('График',schedule),V.field('Смена 1/3',group),
      V.field('Действует с',validFrom),V.field('Причина',note,true),errorBox,
      renderElement('div',{className:'vacation-form-actions',children:[
        renderButton({text:'Сохранить график',className:'button primary',type:'submit'}),
        renderButton({
          text:'Закрыть',className:'button',
          onClick:()=>V.renderEmployees(byId('vacations_employees'))
        })
      ]})
    ],on:{submit:async event=>{
      event.preventDefault();errorBox.textContent='';
      const payload=Object.fromEntries(new FormData(form).entries());
      payload.shift_group=payload.shift_group===''?null:Number(payload.shift_group);
      try{
        await request(`${V.api}/employees/${employee.id}/assignment`,{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(payload)
        });
        notify('Площадка и график изменены');
        await V.load(true);
      }catch(error){
        errorBox.textContent=error.message;
      }
    }}});
    schedule.onchange=()=>{
      group.disabled=schedule.value!=='ONE_THREE';
      if(group.disabled)group.value='';
    };
    schedule.onchange();
    return form;
  };

  V.renderEmployees=(root,editingId=null)=>{
    const employees=V.state.data.employees||[];
    const rows=employees.map(employee=>renderElement('tr',{children:[
      renderElement('td',{children:[
        renderElement('strong',{text:employee.full_name}),
        renderElement('small',{text:employee.role_labels.join(' · ')})
      ]}),
      renderElement('td',{text:employee.site_label}),
      renderElement('td',{text:employee.schedule_label}),
      renderElement('td',{text:employee.shift_label||'—'}),
      renderElement('td',{text:employee.valid_from?`с ${V.dateText(employee.valid_from)}`:'Не задан'}),
      renderElement('td',{children:[
        renderButton({
          text:'Изменить',className:'button',
          onClick:()=>V.renderEmployees(root,Number(employee.id))
        })
      ]})
    ]}));
    root.replaceChildren(...[
      V.pageHead(
        'Сотрудники и графики',
        'Площадка и график меняются с указанной даты; старые отпуска сохраняют историческую привязку.',
        [renderButton({
          text:'Добавить сотрудника',className:'button primary',
          onClick:()=>V.renderEmployees(root,'new')
        })]
      ),
      editingId==='new'?renderElement('section',{className:'vacation-form-card',children:[
        renderElement('h3',{text:'Новый сотрудник'}),
        V.employeeForm(root)
      ]}):null,
      Number.isInteger(editingId)?renderElement('section',{className:'vacation-form-card',children:[
        renderElement('h3',{text:`Новый график: ${V.employeeById(editingId)?.full_name||''}`}),
        V.assignmentEditor(V.employeeById(editingId))
      ]}):null,
      !employees.length?renderElement('div',{
        className:'vacation-empty',
        children:[
          renderElement('h3',{text:'Список сотрудников пока пуст'}),
          renderElement('p',{text:'Добавьте сотрудников, их площадки и графики. Данные сохраняются только в локальной базе отпусков.'})
        ]
      }):null,
      renderElement('div',{className:'table-wrap vacation-table',children:[
        renderElement('table',{children:[
          renderElement('thead',{children:[
            renderElement('tr',{children:
              ['Сотрудник','Площадка','График','Смена','Действует','']
                .map(text=>renderElement('th',{text}))
            })
          ]}),
          renderElement('tbody',{children:rows})
        ]})
      ]}),
      renderElement('p',{
        className:'hint vacation-rule-note',
        text:shiftSummary(employees)
      })
    ].filter(Boolean));
  };
})();
