(function(){
  const V=window.ODE.vacations;

  const checkbox=(name,label)=>renderElement('label',{
    className:'vacation-checkbox',
    children:[
      renderElement('input',{attrs:{name,type:'checkbox',value:'1'}}),
      renderElement('span',{text:label})
    ]
  });

  V.employeeForm=root=>{
    const data=V.state.data;
    const firstName=renderElement('input',{attrs:{
      name:'first_name',maxlength:'100',required:true,autocomplete:'given-name'
    }});
    const lastName=renderElement('input',{attrs:{
      name:'last_name',maxlength:'100',required:true,autocomplete:'family-name'
    }});
    const site=renderSelect({
      name:'site',value:'ixcellerate',options:V.optionRows(data.options.sites)
    });
    const schedule=renderSelect({
      name:'schedule_type',value:'FIVE_TWO',
      options:V.optionRows(data.options.schedules)
    });
    const group=renderSelect({
      name:'shift_group',value:'',options:[
        ['','Не применяется'],['0','Смена 1'],['1','Смена 2'],
        ['2','Смена 3'],['3','Смена 4']
      ]
    });
    const validFrom=renderElement('input',{attrs:{
      name:'valid_from',type:'date',required:true,value:V.isoLocal(new Date())
    }});
    const note=renderElement('input',{attrs:{
      name:'note',maxlength:'1000',placeholder:'Комментарий к назначению'
    }});
    const errorBox=renderElement('div',{
      className:'vacation-form-error',attrs:{role:'alert'}
    });
    const form=renderElement('form',{
      className:'vacation-assignment-form',
      children:[
        V.field('Имя',firstName),V.field('Фамилия',lastName),
        V.field('Площадка',site),V.field('График',schedule),
        V.field('Смена 1/3',group),V.field('Действует с',validFrom),
        V.field('Комментарий',note,true),
        renderElement('div',{className:'vacation-role-options',children:[
          checkbox('is_site_senior','Старший на площадке'),
          checkbox('is_department_head','Начальник отдела'),
          checkbox('is_substitute','Подменный')
        ]}),
        errorBox,
        renderElement('div',{className:'vacation-form-actions',children:[
          renderButton({
            text:'Добавить сотрудника',className:'button primary',type:'submit'
          }),
          renderButton({
            text:'Отмена',className:'button',
            onClick:()=>V.renderEmployees(root)
          })
        ]})
      ],
      on:{submit:async event=>{
        event.preventDefault();errorBox.textContent='';
        const payload=Object.fromEntries(new FormData(form).entries());
        payload.shift_group=payload.shift_group===''?null:Number(payload.shift_group);
        try{
          await request(`${V.api}/employees`,{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify(payload)
          });
          notify('Сотрудник добавлен');
          await V.load(true);
        }catch(error){
          errorBox.textContent=error.message;
        }
      }}
    });
    schedule.onchange=()=>{
      group.disabled=schedule.value!=='ONE_THREE';
      if(group.disabled)group.value='';
    };
    schedule.onchange();
    return form;
  };
})();
