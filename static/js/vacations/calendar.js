(function(){
  const V=window.ODE.vacations;
  V.changeMonth=delta=>{
    const current=V.state.visibleMonth;
    V.state.visibleMonth=new Date(current.getFullYear(),current.getMonth()+delta,1);
    V.state.data=null;V.renderActive();V.load().catch(()=>{});
  };
  V.renderCalendar=root=>{
    const data=V.state.data;
    const title=V.state.visibleMonth.toLocaleDateString('ru-RU',{month:'long',year:'numeric'});
    const controls=renderElement('div',{className:'vacation-month-controls',children:[
      renderButton({text:'←',className:'button',attrs:{'aria-label':'Предыдущий месяц'},onClick:()=>V.changeMonth(-1)}),
      renderElement('strong',{text:title.charAt(0).toLocaleUpperCase()+title.slice(1)}),
      renderButton({text:'→',className:'button',attrs:{'aria-label':'Следующий месяц'},onClick:()=>V.changeMonth(1)})
    ]});
    const weekdays=renderElement('div',{className:'vacation-weekdays',children:V.weekdayNames.map(name=>renderElement('span',{text:name}))});
    const grid=renderElement('div',{className:'vacation-calendar-grid',children:(data.calendar||[]).map(day=>{
      const parsed=V.parseIso(day.date),outside=parsed.getMonth()!==V.state.visibleMonth.getMonth();
      const duty=(day.duty_employees||[]).map(item=>item.full_name).join(', ');
      const chips=(day.vacations||[]).map(item=>renderElement('span',{
        className:`vacation-day-chip ${item.conflict_status==='PENDING'?'conflict':''}`,
        text:item.full_name,
        attrs:{title:`${V.statusLabels[item.sfera_status]||item.sfera_status} · ${V.conflictLabels[item.conflict_status]||item.conflict_status}`}
      }));
      return renderElement('article',{className:`vacation-day${outside?' outside':''}${parsed.getDay()===0||parsed.getDay()===6?' weekend':''}`,children:[
        renderElement('div',{className:'vacation-day-number',children:[
          renderElement('strong',{text:String(parsed.getDate())}),
          renderElement('span',{text:`Смена ${Number(day.duty_shift_group)+1}`})
        ]}),
        duty?renderElement('p',{className:'vacation-duty',text:`Дежурят: ${duty}`}):null,...chips
      ]});
    })});
    root.replaceChildren(
      V.pageHead('Общий календарь','Отпуска, дежурные смены и конфликты IXcellerate и Solar отображаются в одном плане.',[
        renderButton({text:'Добавить отпуск',className:'button primary',onClick:()=>openTask('vacations','vacations_list')})
      ]),
      renderElement('div',{className:'vacation-summary',children:[
        renderCard({title:'Сотрудников',value:String(data.summary.employees)}),
        renderCard({title:'Отпусков в периоде',value:String(data.summary.vacations)}),
        renderCard({title:'Конфликтов ждут решения',value:String(data.summary.pending_conflicts)})
      ]}),
      controls,weekdays,grid,
      renderElement('div',{className:'vacation-legend',children:[
        V.badge('Дежурная смена','duty'),V.badge('Отпуск','leave'),V.badge('Ожидает решения','conflict')
      ]})
    );
  };
})();
