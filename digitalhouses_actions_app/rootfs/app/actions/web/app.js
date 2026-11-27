"use strict";
let model, editing=null, draft=null, dirty=false, busy=false, section="keys";
let parametersBusy=false, parametersError="";
const main=document.querySelector("#main"), notice=document.querySelector("#notice"), scan=document.querySelector("#scan");
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function button(text,fn,cls){const n=el("button",text,cls);n.onclick=fn;return n}
function icon(t,id){
  if(id.startsWith("media_player."))return ["media","plain","Медиаплеер"];
  if(id.startsWith("climate."))return ["climate","plain","Климат"];
  if(id.startsWith("cover."))return ["cover","plain","Шторы"];
  if(id.startsWith("binary_sensor."))return ["window","plain","Датчик окна"];
  if(id.startsWith("switch."))return ["switch","plain","Реле"];
  if(t?.group)return ["group","cct","Группа Zigbee2MQTT"];
  if(t?.rgb)return ["rgb","rgb",t.cct?"RGB + CCT":"RGB"];
  if(t?.cct)return ["cct","cct","CCT"];
  if(t?.brightness)return ["dimmer","cct","Диммируемый"];
  return ["bulb","plain","ON/OFF"];
}
function targetIcon(t,id){
  const [kind,cls,title]=icon(t,id),n=el("span",undefined,"target-icon "+cls);
  n.title=title;n.setAttribute("aria-label",title);
  const ns="http://www.w3.org/2000/svg",svg=document.createElementNS(ns,"svg");
  svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");
  const path=d=>{const p=document.createElementNS(ns,"path");p.setAttribute("d",d);svg.append(p)};
  const circle=(cx,cy,r,fill)=>{const c=document.createElementNS(ns,"circle");c.setAttribute("cx",cx);c.setAttribute("cy",cy);c.setAttribute("r",r);if(fill){c.setAttribute("fill",fill);c.setAttribute("stroke","none")}svg.append(c)};
  if(kind==="media"){path("M6 3h12v18H6Z");circle(12,8,1.5);circle(12,15,3)}
  else if(kind==="climate"){path("M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0ZM12 9v8");circle(12,18,1.5)}
  else if(kind==="cover"){path("M3 3h18M5 4v16h14V4M9 4v16M15 4v16")}
  else if(kind==="window"){path("M4 3h16v18H4ZM12 3v18M4 12h16")}
  else if(kind==="switch"){path("M7 7h10a5 5 0 0 1 0 10H7A5 5 0 0 1 7 7Z");circle(7,12,2.5)}
  else if(kind==="group"){path("M4 11a4 4 0 1 1 8 0c0 2-2 3-2 5H6c0-2-2-3-2-5ZM6 19h4M12 5a4 4 0 0 1 8 0c0 2-2 3-2 5h-4m0 3h4")}
  else if(kind==="dimmer"){circle(12,12,4);path("M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5")}
  else{path("M9 18h6m-5 3h4M9 15c0-2-4-4-4-8a7 7 0 0 1 14 0c0 4-4 6-4 8Z");
    if(kind==="rgb"){circle(9,7,2,"#ef7474");circle(15,7,2,"#82efc7");circle(12,11,2,"#8baaff")}
    if(kind==="cct"){path("M12 4v8");circle(9,8,1.5,"#ffd094");circle(15,8,1.5,"#e9f0f7")}
  }
  n.append(svg);return n;
}
function stat(d){return {same:["●",""],disabled:["Ⅱ","muted"],missing:["✖","danger"],offline:["⚠","problem"],unknown:["?","muted"]}[d.status]||["⚠","problem"]}
function knownState(state){return typeof state==="string"&&!["unknown","unavailable",""].includes(state)}
function targetLabel(id,t){return t?.name&&t.name!==id?id+" - "+t.name:id}
function targetNode(id){const t=model.targets.find(x=>x.entity_id===id);const n=el("span",undefined,"target");n.dataset.entity=id;n.append(targetIcon(t,id),el("span",targetLabel(id,t),"target-label"));if(!t||!knownState(t.state)){const w=el("span","⚠","problem");w.title=t?"Сущность недоступна":"Сущность не найдена";n.append(w)}return n}
async function api(path,data,raw=false){const r=await fetch("api/"+path,data===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:raw?data:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error||"Ошибка");return v}
async function load(){try{model=await api("state");document.querySelector("#app-version").textContent="v"+model.version;document.querySelector("#summary").textContent=section==="parameters"?"Параметры":section==="schedules"?"Расписания ("+(model.schedules||[]).length+")":section==="sensors"?"Датчики ("+(model.sensors||[]).length+")":"Клавиши · устройства ("+model.devices.length+") · Сети Z2M ("+new Set(model.devices.map(d=>d.network).filter(n=>n!=="—")).size+")";notice.classList.toggle("error",!!model.scan.error);scan.disabled=model.scan.state==="updating"||busy;scan.textContent=model.scan.state==="updating"?"Сканирование…":"⟳ Сканировать";if(!editing)renderList();if(!editing&&!busy){if(model.scan.error)notice.textContent=model.scan.error;else if(model.scan.state==="updating")notice.textContent="Сканирование…";else if(model.report){const p=model.report.problems||[];notice.textContent="Последний Scan: "+(model.report.scanned??0)+" устройств · "+p.length+" проблем";notice.title=p.map(x=>x.name+": "+x.reason).join("\n")}}}catch(e){notice.textContent=e.message}}
const keyNames={main:"Основная",left:"Левая",right:"Правая",center:"Центральная"};
const modeNames={"":"Не настроена",control_relay:"Физическая",decoupled:"Логическая","decoupled/ON":"Логическая · ON","decoupled/OFF":"Логическая · OFF"};
const logicalPolicy=p=>["decoupled","decoupled/ON","decoupled/OFF"].includes(p);
function actionAllowed(d,action){
  if(!Object.keys(d.key_modes||{}).length)return d.actions.includes(action);
  const keys=d.key_actions?.[action]||[];
  return keys.length>0&&keys.every(k=>logicalPolicy(d.keep_mode?.[k]));
}
function physicalAction(d,action){
  return (d.key_actions?.[action]||[]).some(k=>d.keep_mode?.[k]==="control_relay");
}
function selectOptions(choices,value,label){
  const select=el("select");
  select.setAttribute("aria-label",label);
  for(const [v,name] of choices){const option=el("option",name);option.value=v;option.disabled=v==="";select.append(option)}
  select.value=value;return select;
}
function formatDuration(seconds){
  return Math.floor(seconds/60)+" мин. "+seconds%60+" сек.";
}
function splitDuration(value){
  return value==null?["",""]:[String(Math.floor(value/60)),String(value%60)];
}
function joinDuration(minutes,seconds,minimum){
  if(minutes===""&&seconds==="")return undefined;
  if(!/^\d*$/.test(minutes)||!/^\d*$/.test(seconds))throw Error("Введите целое число минут и секунд");
  const m=Number(minutes),s=Number(seconds),total=m*60+s;
  if(!Number.isInteger(total)||m>1440||s>59||total<minimum||total>86400)throw Error("Допустимо от "+formatDuration(minimum)+" до 1440 мин. 0 сек.");
  return total;
}
function durationControl(title,value,minimum,onChange){
  const box=el("div",undefined,"duration-control"),caption=el("span",title);
  const [m,s]=splitDuration(value);
  const minutes=el("input"),seconds=el("input");
  for(const [n,label,max,v] of [[minutes,"мин.",1440,m],[seconds,"сек.",59,s]]){
    n.type="number";n.min=0;n.max=max;n.step=1;n.placeholder="—";n.value=v;
    n.setAttribute("aria-label",title+" — "+label);
  }
  const error=el("span","","duration-error problem");
  function changed(){
    update();
    try{
      if(minutes.validity.badInput||seconds.validity.badInput)throw Error("Введите целое число минут и секунд");
      const total=joinDuration(minutes.value,seconds.value,minimum);
      error.textContent="";minutes.setCustomValidity("");seconds.setCustomValidity("");
      onChange(total);
    }catch(e){
      error.textContent=e.message;minutes.setCustomValidity(e.message);seconds.setCustomValidity(e.message);
    }
  }
  minutes.oninput=seconds.oninput=changed;
  const ml=el("label"),sl=el("label");
  ml.append(minutes,document.createTextNode("мин."));sl.append(seconds,document.createTextNode("сек."));
  const clear=button("×",()=>{minutes.value=seconds.value="";changed()},"duration-clear");
  clear.type="button";clear.title="Отключить таймер";clear.setAttribute("aria-label","Отключить таймер");
  box.append(caption,ml,sl,clear,error);
  return box;
}
function modeControls(){
  const panel=el("div",undefined,"key-modes");
  for(const key of Object.keys(draft.key_modes||{})){
    const row=el("div",undefined,"key-mode");
    const policy=draft.keep_mode?.[key]||"";
    const select=selectOptions([["","Выберите тип"],["control_relay","Физическая"],["decoupled","Логическая"]],
      logicalPolicy(policy)?"decoupled":policy,"Тип клавиши "+(keyNames[key]||key));
    select.onchange=()=>{
      draft.keep_mode??={};
      draft.keep_mode[key]=select.value;
      if(select.value!=="control_relay"&&draft.relay_timers)delete draft.relay_timers[key];
      draft.enabled=true;update();renderEdit();
    };
    row.append(el("strong",keyNames[key]||key),select);
    if(logicalPolicy(policy)){
      const hold=selectOptions([["","Выберите ON/OFF"],["ON","ON"],["OFF","OFF"]],
        policy.includes("/")?policy.split("/")[1]:"","Удерживать реле "+(keyNames[key]||key));
      hold.onchange=()=>{draft.keep_mode[key]="decoupled/"+hold.value;update();renderEdit()};
      const label=el("label");label.append(document.createTextNode("Удерживать"),hold);row.append(label);
    }
    if(policy==="control_relay"){
      row.append(durationControl("Авто-OFF после включения",draft.relay_timers?.[key],1,total=>{
        draft.relay_timers??={};
        if(total===undefined)delete draft.relay_timers[key];else draft.relay_timers[key]=total;
      }));
    }
    panel.append(row);
  }
  return panel;
}
function deviceTitle(d){return d.ha_name&&d.ha_name!==d.name?d.name+" - "+d.ha_name:d.name}
function renderParameters(){
  const panel=el("article"),label=el("label",undefined,"live-parameter"),description=el("div");
  const title="Применять параметры при переходе День/Ночь";
  description.append(el("strong",title),el("div","При смене внешнего режима обновлять параметры уже работающих устройств с профилем День/Ночь. Не включать выключенные светильники и не запускать музыку.","muted"));
  const check=el("input");check.type="checkbox";check.setAttribute("role","switch");check.setAttribute("aria-label",title);
  check.checked=model.auto_day_night===true;check.disabled=parametersBusy;
  check.onchange=async()=>{
    const requested=check.checked;
    parametersBusy=true;parametersError="";check.disabled=true;
    try{
      const result=await api("parameters",{auto_day_night:requested});
      model.auto_day_night=result.auto_day_night;
    }catch(e){parametersError=e.message}
    finally{parametersBusy=false;await load();if(section==="parameters")renderParameters()}
  };
  label.append(description,check);panel.append(label);
  if(parametersBusy)panel.append(el("div","Сохранение…","muted"));
  if(parametersError)panel.append(el("div",parametersError,"problem"));
  main.replaceChildren(panel);
}
function renderList(){
if(section==="parameters"){renderParameters();return}
if(section==="schedules"){renderSchedules();return}
if(section==="sensors"){renderSensors();return}
const focused=main.contains(document.activeElement)?document.activeElement.dataset.deviceId:null;
main.replaceChildren();for(const d of model.devices){const a=el("article"),h=el("div",undefined,"head"),info=el("div",undefined,"device-info"),[sym,cls]=stat(d),status=el("span",sym+" ", "status "+cls);status.title=d.reason||d.status;const name=el("strong",undefined,"device-name");name.append(status,document.createTextNode(d.name));
if(d.ha_name&&d.ha_name!==d.name)name.append(el("span"," - "+d.ha_name,"ha-device-name"));info.append(name,el("div",d.model+" · "+d.room+" · "+d.network,"muted"));
if(d.power_meter)info.append(el("span",Number.isFinite(d.power_w)?d.power_w+" W":"— W","muted"));
for(const [key,mode] of Object.entries(d.key_modes||{})){
  const seconds=d.relay_timers?.[key],remaining=d.relay_remaining?.[key];
  info.append(el("span",(keyNames[key]||key)+": "+modeNames[mode]+(seconds?" · Авто-OFF "+formatDuration(seconds):"")+(remaining!=null?" · Осталось "+formatDuration(remaining):""),"key-summary muted"));
}const gear=el("span","⚙","settings");gear.setAttribute("aria-hidden","true");h.append(info,gear);
a.classList.add("device-card");a.tabIndex=0;a.setAttribute("role","button");
a.setAttribute("aria-label","Настроить "+deviceTitle(d));a.dataset.deviceId=d.id;
a.onclick=()=>open(d);
a.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();open(d)}};a.append(h);const b=el("div",undefined,"bindings");for(const [action,targets] of Object.entries(d.bindings)){const x=el("span",undefined,"binding");x.dataset.device=d.name;x.dataset.network=d.network;x.dataset.action=action;x.append(el("span",action+" →"));for(const t of targets){
  x.append(targetNode(t.entity_id));
  if(t.off_delay_seconds!=null){
    const due=d.key_deadlines?.[action]?.[t.entity_id];
    x.append(el("span","Авто-OFF "+formatDuration(t.off_delay_seconds)+(due!=null?" · Осталось "+formatDuration(Math.max(0,Math.ceil(due-Date.now()/1000))):""),"muted"));
  }
}if(d.disabled_actions?.includes(action))x.append(el("span","Ⅱ","muted"));if(!actionAllowed(d,action))x.append(el("span","⚠","problem"));b.append(x)}if(!b.children.length)b.append(el("span","Нет привязок","muted"));a.append(b);main.append(a);if(focused===d.id)a.focus({preventScroll:true})}applyLiveState()}
function open(d){editing=d;draft=structuredClone(d);draft.disabled_actions??=[];draft.revision=model.revision;dirty=false;renderEdit()}
function goBack(){if(dirty&&!confirm("Отменить несохранённые изменения?"))return;editing=null;draft=null;dirty=false;renderList();load()}
function update(){dirty=true}
function addParam(parent,t,a,key,label,min,max,step){const wrap=el("label"),check=el("input");check.type="checkbox";check.checked=Object.hasOwn(a.data,key);const input=el("input");input.type="number";input.min=min;input.max=max;input.step=step;input.value=a.data[key]??min;input.disabled=!check.checked;check.onchange=()=>{if(check.checked)a.data[key]=Number(input.value);else delete a.data[key];input.disabled=!check.checked;update();if(key==="color_temp_kelvin")renderEdit()};input.onchange=()=>{a.data[key]=Number(input.value);update()};wrap.append(check,document.createTextNode(label),input);parent.append(wrap)}
const testRequests=new Map(),testErrors=new Map();
function lightTestControl(t,id){
  if(!id.startsWith("light."))return null;
  const wrap=el("span",undefined,"light-test");wrap.dataset.testEntity=id;
  const state=el("span","—","light-test-state");
  const test=button("Тест",()=>requestLightTest(id),"light-test-button");
  test.type="button";test.setAttribute("aria-label","Тест "+id);
  const result=el("span","","light-test-result muted");
  wrap.append(state,test,result);updateTestControl(wrap);return wrap;
}
function latestTest(id){
  let latest=null;
  for(const row of journal.values())if(row.action==="TEST"&&row.targets[id]&&(!latest||row.id>latest.id))latest=row;
  return latest?.targets[id];
}
function updateTestControl(wrap){
  const id=wrap.dataset.testEntity,t=model?.targets.find(x=>x.entity_id===id);
  const state=liveStates[id]??t?.state;
  const result=latestTest(id),pending=testRequests.has(id)||["queued","sent"].includes(result?.status);
  const label=wrap.querySelector(".light-test-state"),b=wrap.querySelector("button"),note=wrap.querySelector(".light-test-result");
  label.textContent=["on","off"].includes(state)?state.toUpperCase():"—";
  label.title=!t?"Не найдено":["on","off"].includes(state)?"Наблюдаемое состояние":"Недоступно или состояние неизвестно";
  const row=wrap.closest(".picker-line")?.querySelector(".picker-result")||wrap.closest(".assigned");
  markIcon(row?.querySelector(".target-icon"),state);
  label.classList.toggle("is-on",state==="on");b.disabled=!!model?.maintenance_mode||!t||!["on","off"].includes(state)||pending;
  b.textContent=pending?"…":"Тест";
  note.textContent=testErrors.get(id)||({queued:"В очереди",sent:"Ожидается состояние",confirmed:"✓✓",skipped:"Не выполнено",timeout:"Нет подтверждения",superseded:"Заменено"}[result?.status]||"");
  note.title=testErrors.get(id)||result?.reason||"";
}
async function requestLightTest(id){
  if(testRequests.has(id))return;
  testErrors.delete(id);testRequests.set(id,null);applyLiveState();
  try{
    const response=await api("test-light",{entity_id:id});
    testRequests.set(id,response.id);
    // If the journal already received this row while HTTP was in flight,
    // hand the state back to that authoritative journal immediately.
    if(journal.has(response.id))testRequests.delete(id);
    await pollLog();
  }catch(e){testRequests.delete(id);testErrors.set(id,e.message)}
  applyLiveState();
}
const coverLabels={toggle:"Toggle",open:"Открыть",close:"Закрыть",stop:"Стоп",position:"Положение"};
function coverControls(action,a,t,row){
  const p=el("div",undefined,"params");
  const state=liveStates[a.entity_id]??t?.state;
  p.append(el("span","Состояние: "+(state||"—"),"muted"));
  if(a.operation==="position"){
    const n=el("input");n.type="number";n.min=0;n.max=100;n.step=1;n.value=a.data.position;
    n.onchange=()=>{a.data.position=Number(n.value);update()};
    const l=el("label","Положение %");l.append(n);p.append(l);
  }
  const sensors=a.data.window_sensors||[];
  p.append(button(sensors.length?"Окна ("+sensors.length+")":"+ Защита окна",()=>{
    DHActionsEntityPicker.open({items:model.targets,values:sensors,domains:["binary_sensor"],
      areaId:draft.area_id,areaHint:draft.room,renderIcon:targetIcon,
      onConfirm:ids=>{
        if(ids.length)a.data.window_sensors=ids;else delete a.data.window_sensors;
        update();renderEdit(action);
      }});
  }));
  for(const id of sensors){
    const sensor=model.targets.find(x=>x.entity_id===id);
    const label=sensor?.name&&sensor.name!==id?sensor.name+" · "+id:id;
    p.append(el("span",label,"window-guard-name"+(sensor?" muted":" problem")));
  }
  if(sensors.length)p.append(el("span","Защита действует на все назначения этой шторы","muted"));
  row.append(p);
}
const climateLabels={toggle:"Toggle",on:"ON",off:"OFF",hvac_mode:"Режим HVAC",temperature:"Температура"};
const hvacLabels={off:"OFF",heat:"Отопление",cool:"Охлаждение",heat_cool:"Отопление / охлаждение",auto:"Авто",dry:"Осушение",fan_only:"Вентиляция"};
function assignmentOperations(a,t){
  if(/^(climate|cover|media_player)\./.test(a.entity_id)){
    const labels=a.entity_id.startsWith("media_player.")?mediaLabels:a.entity_id.startsWith("climate.")?climateLabels:coverLabels;
    return [...new Set([...(t?.operations||[]),a.operation])].map(v=>[v,labels[v]||v]);
  }
  return [["toggle","Toggle"],["on","ON"],["off","OFF"]];
}
function climateControls(a,t,row){
  const p=el("div",undefined,"params");
  const state=liveStates[a.entity_id]??t.state;
  p.append(el("span","Режим: "+(hvacLabels[state]||state||"—"),"muted"));
  if(Number.isFinite(t.temperature))p.append(el("span","Задано: "+t.temperature+" "+(t.temperature_unit||""),"muted"));
  if(a.operation==="hvac_mode"){
    const select=selectOptions([["","Выберите режим"],...[...new Set([...(t.hvac_modes||[]),a.data.hvac_mode].filter(Boolean))].map(v=>[v,hvacLabels[v]||v])],a.data.hvac_mode||"","Режим HVAC");
    select.onchange=()=>{a.data.hvac_mode=select.value;update()};
    const label=el("label","Режим HVAC");label.append(select);p.append(label);
  }else if(a.operation==="temperature"){
    const n=el("input");n.type="number";n.min=t.min_temp??"";n.max=t.max_temp??"";n.step=t.target_temp_step??"any";
    n.value=a.data.temperature??"";n.onchange=()=>{a.data.temperature=n.value===""?null:Number(n.value);update()};
    const label=el("label","Температура "+(a.data.temperature_unit||""));label.append(n);p.append(label);
    if(a.data.temperature_unit!==t.temperature_unit)p.append(el("span","Единица температуры HA изменилась — выберите операцию заново","problem"));
    else if(Number.isFinite(t.min_temp)&&Number.isFinite(t.max_temp))p.append(el("span",t.min_temp+"–"+t.max_temp+" "+t.temperature_unit+(t.target_temp_step?" · шаг "+t.target_temp_step:""),"muted"));
  }
  row.append(p);
}
const mediaLabels={play_pause:"Play / Pause",play:"Play",pause:"Pause",stop:"Stop",next:"Следующий трек",previous:"Предыдущий трек",volume:"Громкость",play_media:"Воспроизвести медиа"};
function chooseMedia(a,action){
  const dialog=el("dialog",undefined,"entity-picker");
  const head=el("div",undefined,"head"),list=el("div",undefined,"picker-results"),trail=[];
  const close=()=>{dialog.close();dialog.remove()};
  const back=button("← Назад",()=>{trail.pop();loadMedia(trail.at(-1))});
  head.append(el("h2","Выбор медиа"),back,button("Закрыть",close));dialog.append(head,list);
  dialog.addEventListener("cancel",e=>{e.preventDefault();close()});
  let request=0;
  async function loadMedia(ref){
    const seq=++request;back.disabled=!trail.length;list.replaceChildren(el("span","Загрузка…","muted"));
    try{
      const result=await api("browse-media",{entity_id:a.entity_id,...(ref?{ref}:{})});
      if(seq!==request||!dialog.isConnected)return;
      list.replaceChildren();
      for(const item of result.children){
        const line=el("div",undefined,"picker-line");
        line.append(el("span",item.title,"picker-info"));
        if(item.can_expand)line.append(button("Открыть",()=>{trail.push({media_content_id:item.media_content_id,media_content_type:item.media_content_type});loadMedia(trail.at(-1))}));
        if(item.can_play)line.append(button("Выбрать",()=>{
          a.data={media_content_id:item.media_content_id,media_content_type:item.media_content_type,title:item.title};
          close();update();renderEdit(action);
        }));
        list.append(line);
      }
      if(!result.children.length)list.append(el("span","Нет доступных медиа","muted"));
      if(result.truncated)list.append(el("span","Показаны первые 500 элементов","muted"));
    }catch(e){if(seq===request&&dialog.isConnected)list.replaceChildren(el("span",e.message,"problem"))}
  }
  document.body.append(dialog);dialog.showModal();loadMedia();
}
function mediaControls(a,t,row,action){
  const p=el("div",undefined,"params");
  p.append(el("span","Состояние: "+(liveStates[a.entity_id]??t.state??"—"),"muted"));
  if(a.operation==="volume"&&profileSelect(a,t,p,action,true)){
    const n=el("input");n.type="number";n.min=0;n.max=100;n.step=1;n.value=a.data.volume_pct??"";
    n.onchange=()=>{a.data.volume_pct=n.value===""?null:Number(n.value);update()};
    const label=el("label","Громкость %");label.append(n);p.append(label);
  }else if(a.operation==="play_media"){
    p.append(button(a.data.title?"Изменить медиа":"Выбрать медиа",()=>chooseMedia(a,action)));
    if(a.data.title)p.append(el("span",a.data.title,"muted"));
  }
  row.append(p);
}
const customDrafts=new WeakSet();
function profileSelect(a,t,p,action,volume=false){
  const saved=a.data.profile;
  const kind=saved==="current"?"current":saved||Object.keys(a.data).length||customDrafts.has(a)?"fixed":"simple";
  const mode=el("select");
  for(const [value,title] of [...(volume?[]:[["simple","ON/OFF"]]),["fixed","Фиксированные"],["current","День/Ночь"]]){
    const option=el("option",title);option.value=value;mode.append(option);
  }
  mode.value=volume&&kind==="simple"?"fixed":kind;
  mode.onchange=()=>{
    customDrafts.delete(a);
    const color=a.data.color_source;
    a.data=mode.value==="current"?{profile:"current"}:mode.value==="fixed"?{profile:"day"}:{};
    if(a.data.profile&&color&&!volume)a.data.color_source=color;
    update();renderEdit(action);
  };
  p.append(mode);
  if(mode.value==="fixed"){
    const select=el("select");
    for(const [value,title] of [["day","День"],["night","Ночь"],["custom","Свои"]]){
      const o=el("option",title);o.value=value;select.append(o);
    }
    select.value=saved==="day"||saved==="night"?saved:"custom";
    select.onchange=()=>{
      if(select.value==="custom")customDrafts.add(a);else customDrafts.delete(a);
      const color=a.data.color_source;
      a.data=select.value==="custom"?(volume?{volume_pct:t.volume_pct??null}:{}):{profile:select.value};
      if(a.data.profile&&color&&!volume)a.data.color_source=color;
      update();renderEdit(action);
    };
    p.append(select);
    if(select.value==="custom")return true;
  }
  if(a.data.profile){
    if(!volume&&t.cct&&t.rgb){
      const label=el("label","Источник цвета"),color=el("select");
      for(const [value,title] of [["","Выберите CCT или RGB"],["cct","CCT — температура"],["rgb","RGB — цвет"]]){
        const o=el("option",title);o.value=value;color.append(o);
      }
      color.value=a.data.color_source||"";
      color.required=true;
      color.onchange=()=>{if(color.value)a.data.color_source=color.value;else delete a.data.color_source;update();renderEdit(action)};
      label.append(color);p.append(label);
      if(!a.data.color_source)p.append(el("span","⚠ Укажите источник цвета для глобального профиля","problem"));
    }
    p.append(el("span",model.home_profiles_ready&&(a.data.profile!=="current"||model.home_mode)?"Глобальные параметры дома":"Глобальные параметры недоступны","muted"));
  }
  return false;
}
function lightProfileControls(a,t,row,action){
  const p=el("div",undefined,"params");
  if(a.operation==="off"){
    if(t.transition&&Object.hasOwn(a.data,"transition"))addParam(p,t,a,"transition","Transition, сек",0,60,.1);
    row.append(p);return;
  }
  if(!(t.brightness||t.cct||t.rgb)&&!Object.keys(a.data).length)return;
  if(profileSelect(a,t,p,action)){
if(a.operation!=="off"){if(t.brightness)addParam(p,t,a,"brightness_pct","Яркость %",0,100,1);if(t.cct&&Number.isInteger(t.min_kelvin)&&Number.isInteger(t.max_kelvin)&&!Object.hasOwn(a.data,"rgb_color"))addParam(p,t,a,"color_temp_kelvin","Kelvin",t.min_kelvin,t.max_kelvin,1);if(t.rgb&&!Object.hasOwn(a.data,"color_temp_kelvin")){const l=el("label"),c=el("input"),picker=el("input");c.type="checkbox";c.checked=Object.hasOwn(a.data,"rgb_color");picker.type="color";picker.value="#"+(a.data.rgb_color||[255,255,255]).map(v=>v.toString(16).padStart(2,"0")).join("");picker.disabled=!c.checked;c.onchange=()=>{if(c.checked)a.data.rgb_color=[1,3,5].map(i=>parseInt(picker.value.slice(i,i+2),16));else delete a.data.rgb_color;update();renderEdit(action)};picker.oninput=()=>{a.data.rgb_color=[1,3,5].map(i=>parseInt(picker.value.slice(i,i+2),16));update()};l.append(c,document.createTextNode("RGB"),picker);p.append(l)}}if(t.transition)addParam(p,t,a,"transition","Transition, сек",0,60,.1);
  }
  row.append(p);
}
function scheduleOperations(a,t){
  return assignmentOperations(a,t).filter(([op])=>!["toggle","play_pause","next","previous"].includes(op));
}
const nightEditors=new WeakMap();
const sensorWhenNames={always:"Всегда",day:"День",night:"Ночь"};
function sensorModeControls(action,a,t,row){
  const p=el("div",undefined,"params"),label=el("label","Включать");
  const when=selectOptions(Object.entries(sensorWhenNames),a.when||"always","Режим включения");
  when.onchange=()=>{
    if(when.value==="always")delete a.when;else a.when=when.value;
    if(when.value!=="always"){delete a.night_data;nightEditors.delete(a)}
    update();renderEdit(action);
  };
  label.append(when);p.append(label);
  if(a.entity_id.startsWith("light.")&&(t.brightness||t.cct||t.rgb)&&(a.when||"always")==="always"){
    const separate=el("input");separate.type="checkbox";separate.checked=Object.hasOwn(a,"night_data");
    const text=el("label");text.append(separate,document.createTextNode("Отдельные параметры ночью"));
    separate.onchange=()=>{
      if(separate.checked)a.night_data=structuredClone(a.data);
      else{delete a.night_data;nightEditors.delete(a)}
      update();renderEdit(action);
    };
    p.append(text);
  }
  row.append(p);
}
function sensorLightControls(a,t,row,action){
  if(!Object.hasOwn(a,"night_data")){lightProfileControls(a,t,row,action);return}
  const day=el("div",undefined,"sensor-profile"),night=el("div",undefined,"sensor-profile");
  day.append(el("strong","День"));lightProfileControls(a,t,day,action);
  let editor=nightEditors.get(a);
  if(!editor){
    editor={entity_id:a.entity_id,operation:"on",get data(){return a.night_data},set data(value){a.night_data=value}};
    nightEditors.set(a,editor);
  }
  night.append(el("strong","Ночь"));lightProfileControls(editor,t,night,action);
  row.append(day,night);
}
function assignedRow(action,a,container){const t=model.targets.find(t=>t.entity_id===a.entity_id),row=el("div",undefined,"assigned");row.append(targetIcon(t,a.entity_id),el("strong",(t?.name||a.entity_id)+" · "+a.entity_id));const op=el("select");for(const [v,n] of (editing?.sensor?[["on","ON"]]:editing?.schedule?scheduleOperations(a,t):assignmentOperations(a,t))){const o=el("option",n);o.value=v;op.append(o)}op.value=a.operation;op.onchange=()=>{a.operation=op.value;
if(a.entity_id.startsWith("cover.")){if(op.value==="position")a.data.position=50;else delete a.data.position}
else if(/^(climate|media_player)\./.test(a.entity_id))a.data=DHActionsEntityPicker.initialData(op.value,t);
if(op.value==="off"){delete a.off_delay_seconds;for(const k of Object.keys(a.data))if(k!=="transition")delete a.data[k];}update();renderEdit(action)};const test=lightTestControl(t,a.entity_id);if(test)row.append(test);row.append(op,button("Удалить",()=>{draft.bindings[action]=draft.bindings[action].filter(x=>x.entity_id!==a.entity_id);if(!draft.bindings[action].length){delete draft.bindings[action];draft.disabled_actions=draft.disabled_actions.filter(x=>x!==action)}update();renderEdit(action)}));if(!t){row.append(el("span","⚠ Сущность отсутствует","problem"));container.append(row);return}if(a.entity_id.startsWith("cover."))coverControls(action,a,t,row);if(a.entity_id.startsWith("climate."))climateControls(a,t,row);if(a.entity_id.startsWith("media_player."))mediaControls(a,t,row,action);if(editing?.sensor)sensorModeControls(action,a,t,row);
if(a.entity_id.startsWith("light.")){if(editing?.sensor)sensorLightControls(a,t,row,action);else lightProfileControls(a,t,row,action);}
if(!editing?.schedule&&(editing?.sensor||(/^(light|switch)\./.test(a.entity_id)&&["on","toggle"].includes(a.operation)))){
  const p=el("div",undefined,"params");
  p.append(durationControl(editing?.sensor?"Авто-OFF после отсутствия":"Авто-OFF после включения",a.off_delay_seconds,editing?.sensor?0:1,total=>{
    if(total===undefined)delete a.off_delay_seconds;else a.off_delay_seconds=total;
  }));
  row.append(p);
}
container.append(row)}
function actionGroup(action){const p=action.match(/_(left|right|center|plus|minus|both|[0-9]+)$/)||action.match(/^(button_[0-9]+)_/);return p?p[1]:"Нажатия"}
function renderEdit(expand){if(editing?.schedule){renderScheduleEdit();return}if(editing?.sensor){renderSensorEdit();return}main.replaceChildren();const h=el("div",undefined,"head");h.append(button("← Клавиши",goBack),el("h2",deviceTitle(draft)+" · "+draft.room),button("Сохранить",save,"save"));main.append(h);const enabled=el("input");enabled.type="checkbox";enabled.checked=draft.enabled;enabled.onchange=()=>{draft.enabled=enabled.checked;update()};const l=el("label");l.append(enabled,document.createTextNode("Включено"));const controls=el("div",undefined,"editor-controls");controls.append(l);main.append(controls);
if(Object.keys(draft.key_modes||{}).length)main.append(modeControls());
const possible=Object.keys(draft.key_modes||{}).length?Object.keys(draft.key_actions):draft.actions;
let group=null;const ordered=[...new Set([...possible.filter(a=>actionAllowed(draft,a)),...Object.keys(draft.bindings)])].sort((a,b)=>actionGroup(a).localeCompare(actionGroup(b))||a.localeCompare(b));for(const action of ordered){const next=actionGroup(action);if(next!==group){main.append(el("h2",next==="Нажатия"?next:"Клавиша "+next));group=next;}if(physicalAction(draft,action)){
  const row=el("div",undefined,"assigned");
  row.append(el("span",action+" · удалите прежнее назначение перед сохранением","problem"),
    button("Удалить назначение",()=>{delete draft.bindings[action];draft.disabled_actions=draft.disabled_actions.filter(x=>x!==action);update();renderEdit()}));
  main.append(row);continue;
}
const allowed=actionAllowed(draft,action),detail=el("details",undefined,"action");detail.open=action===expand||(!expand&&!!draft.bindings[action]);detail.append(el("summary",action+" · "+(draft.bindings[action]||[]).map(a=>targetLabel(a.entity_id,model.targets.find(t=>t.entity_id===a.entity_id))).join(", ")+(allowed?"":" ⚠")));if(draft.bindings[action]){const c=el("input");c.type="checkbox";c.checked=!draft.disabled_actions.includes(action);c.onchange=()=>{draft.disabled_actions=c.checked?draft.disabled_actions.filter(x=>x!==action):[...draft.disabled_actions,action];update()};const l=el("label");l.append(c,document.createTextNode("Назначение активно"));detail.append(l)}for(const a of draft.bindings[action]||[])assignedRow(action,a,detail);if(allowed){
  const existing=draft.bindings[action]||[];
  detail.append(button(existing.length?"Изменить выбор сущностей":"+ Выбрать сущности",()=>{
    const usage={};
    for(const device of model.devices)for(const [press,assignments] of Object.entries(device.bindings))
      for(const item of assignments)(usage[item.entity_id]??=[]).push(device.name+" / "+press);
    DHActionsEntityPicker.open({items:model.targets,values:existing.map(a=>a.entity_id),
      areaId:draft.area_id,areaHint:draft.room,usage,renderIcon:targetIcon,renderTest:lightTestControl,
      onConfirm:ids=>{
        if(JSON.stringify(ids)===JSON.stringify(existing.map(a=>a.entity_id)))return;
        if(ids.length){draft.bindings[action]=DHActionsEntityPicker.mergeAssignments(existing,ids,model.targets);draft.enabled=true}
        else{delete draft.bindings[action];draft.disabled_actions=draft.disabled_actions.filter(a=>a!==action)}
        update();renderEdit(action);
      }});
  }));
}main.append(detail)}}
async function save(){try{
  const invalid=main.querySelector(".duration-control input:invalid")||main.querySelector(".params select:invalid");
  if(invalid){invalid.reportValidity();return}
  if(editing?.schedule){
    const config={entity_id:draft.id,name:draft.name.trim(),enabled:draft.enabled,trigger:draft.trigger,catch_up:!!draft.catch_up,assignments:draft.bindings.schedule||[]};
    await api("save-schedule",{revision:draft.revision,config});
    editing=null;draft=null;dirty=false;notice.textContent="Сохранено";await load();return;
  }
  if(editing?.sensor){
    const config={entity_id:draft.id,enabled:draft.enabled,assignments:draft.bindings.presence||[]};
    if(draft.lux_entity_id){config.lux_entity_id=draft.lux_entity_id;config.lux_threshold=draft.lux_threshold??null}
    await api("save-sensor",{revision:draft.revision,config});
    editing=null;draft=null;dirty=false;notice.textContent="Сохранено";await load();return;
  }
  for(const [key,policy] of Object.entries(draft.keep_mode||{}))
    if(policy==="decoupled"&&editing.keep_mode?.[key]!=="decoupled")
      throw Error("Выберите, удерживать ON или OFF: "+(keyNames[key]||key));
  await api("save",{id:draft.id,revision:draft.revision,enabled:draft.enabled,bindings:draft.bindings,disabled_actions:draft.disabled_actions,...(Object.keys(draft.key_modes||{}).length?{keep_mode:draft.keep_mode||{},relay_timers:draft.relay_timers||{}}:{})});dirty=false;editing=null;notice.textContent="Сохранено";await load()}catch(e){notice.textContent=e.message}}
scan.onclick=async()=>{busy=true;scan.disabled=true;try{await api("scan",{});notice.textContent="Сканирование запущено"}catch(e){notice.textContent=e.message}finally{busy=false;await load()}};
function selectSection(next){
  if(dirty&&!confirm("Отменить несохранённые изменения?"))return;
  section=next;editing=null;draft=null;dirty=false;
  document.querySelector("#devices-nav").classList.toggle("active",next==="keys");
  document.querySelector("#sensors-nav").classList.toggle("active",next==="sensors");
  document.querySelector("#schedules-nav").classList.toggle("active",next==="schedules");
  document.querySelector("#parameters-nav").classList.toggle("active",next==="parameters");
  if(model)renderList();load();
}
document.querySelector("#devices-nav").onclick=()=>selectSection("keys");
document.querySelector("#sensors-nav").onclick=()=>selectSection("sensors");
document.querySelector("#schedules-nav").onclick=()=>selectSection("schedules");
document.querySelector("#parameters-nav").onclick=()=>selectSection("parameters");
function triggerLabel(trigger){
  if(trigger.kind==="time")return trigger.time;
  const n=trigger.offset_minutes;
  return (trigger.kind==="sunrise"?"Рассвет":"Закат")+(n?" "+(n>0?"+":"−")+Math.abs(n)+" мин.":"");
}
function renderSchedules(){
  main.replaceChildren();
  const header=el("div",undefined,"head");
  header.append(el("span",model.schedule_timezone?"Время HA: "+model.schedule_timezone:"Время HA не подтверждено","muted"),
    button("+ Добавить расписание",()=>{
      const id="schedule."+Array.from(crypto.getRandomValues(new Uint8Array(12)),b=>b.toString(16).padStart(2,"0")).join("");
      openSchedule({entity_id:id,name:"",enabled:false,trigger:{kind:"time",time:"08:00"},assignments:[]},true);
    }));
  main.append(header);
  for(const schedule of model.schedules||[]){
    const card=el("article",undefined,"device-card");card.tabIndex=0;card.setAttribute("role","button");
    card.append(el("strong",(schedule.enabled?"● ":"Ⅱ ")+schedule.name),el("div","Ежедневно · "+triggerLabel(schedule.trigger)+(schedule.catch_up?" · С учётом перезапуска":""),"muted"));
    const targets=el("div",undefined,"bindings");
    for(const a of schedule.assignments){
      const line=el("div",undefined,"binding");
      line.append(targetNode(a.entity_id),el("span",scheduleOperations(a,model.targets.find(t=>t.entity_id===a.entity_id)).find(([op])=>op===a.operation)?.[1]||a.operation,"muted"));
      targets.append(line);
    }
    card.append(targets);card.onclick=()=>openSchedule(schedule);
    card.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();openSchedule(schedule)}};
    main.append(card);
  }
  if(!(model.schedules||[]).length)main.append(el("p","Нет расписаний","muted"));
  applyLiveState();
}
function openSchedule(schedule,isNew=false){
  editing={...schedule,schedule:true,isNew};
  draft={id:schedule.entity_id,name:schedule.name,enabled:schedule.enabled,catch_up:!!schedule.catch_up,trigger:structuredClone(schedule.trigger),
         bindings:{schedule:structuredClone(schedule.assignments).map(a=>({...a,data:a.data||{}}))},revision:model.revision,disabled_actions:[]};
  dirty=false;renderScheduleEdit();
}
function renderScheduleEdit(){
  main.replaceChildren();
  const h=el("div",undefined,"head");h.append(button("← Расписания",goBack),el("h2","Расписание"),button("Сохранить",save,"save"));
  if(!editing.isNew)h.append(button("Удалить",async()=>{
    if(!confirm("Удалить расписание "+editing.name+"?"))return;
    try{await api("delete-schedule",{revision:draft.revision,entity_id:draft.id});editing=null;draft=null;dirty=false;await load()}catch(e){notice.textContent=e.message}
  }));
  main.append(h);
  const name=el("input");name.type="text";name.maxLength=100;name.value=draft.name;name.placeholder="Например: Шторы утром";
  name.oninput=()=>{draft.name=name.value;update()};
  const nl=el("label","Название");nl.append(name);
  const enabled=el("input");enabled.type="checkbox";enabled.checked=draft.enabled;enabled.onchange=()=>{draft.enabled=enabled.checked;update()};
  const en=el("label");en.append(enabled,document.createTextNode("Включено"));
  const settings=el("div",undefined,"schedule-settings");settings.append(nl,en);
  const trigger=selectOptions([["time","Время"],["sunrise","Рассвет"],["sunset","Закат"]],draft.trigger.kind,"Ежедневно");
  trigger.onchange=()=>{draft.trigger=trigger.value==="time"?{kind:"time",time:"08:00"}:{kind:trigger.value,offset_minutes:0};update();renderScheduleEdit()};
  const tl=el("label","Ежедневно");tl.append(trigger);settings.append(tl);
  if(draft.trigger.kind==="time"){
    const time=el("input");time.type="time";time.value=draft.trigger.time;time.onchange=()=>{draft.trigger.time=time.value;update()};
    const label=el("label","Время");label.append(time);settings.append(label);
  }else{
    const n=el("input");n.type="number";n.min=-720;n.max=720;n.step=1;n.value=draft.trigger.offset_minutes;
    n.oninput=()=>{draft.trigger.offset_minutes=n.value===""?null:Number(n.value);update()};
    const label=el("label","Смещение, мин.");label.append(n);settings.append(label,el("span","− раньше, + позже","muted"));
  }
  const recovery=el("input");recovery.type="checkbox";recovery.checked=draft.catch_up;
  const incompatible=(draft.bindings.schedule||[]).some(a=>! /^(light|switch)\./.test(a.entity_id)||!["on","off"].includes(a.operation));
  recovery.disabled=incompatible&&!draft.catch_up;
  recovery.onchange=()=>{draft.catch_up=recovery.checked;update();renderScheduleEdit()};
  const recoveryLabel=el("label");recoveryLabel.append(recovery,document.createTextNode("Выполнять пропущенное при перезапуске HAOS"));
  settings.append(recoveryLabel,el("span",incompatible?"Компенсация доступна только для Light/Switch ON/OFF.":"Однократно после готовности системы; только последнее актуальное событие за 24 ч.","muted"));
  settings.append(el("span",model.schedule_timezone?"Часовой пояс HA: "+model.schedule_timezone:"Часовой пояс HA недоступен","muted"));
  main.append(settings,el("h2","Действия"));
  const action="schedule",existing=draft.bindings[action]||[];
  for(const a of existing)assignedRow(action,a,main);
  main.append(button(existing.length?"Изменить выбор сущностей":"+ Выбрать сущности",()=>{
    const eligible=t=>/^(light|switch)\./.test(t.entity_id)||(!draft.catch_up&&/^(cover|climate|media_player)\./.test(t.entity_id)&&(t.operations||[]).some(op=>!["toggle","play_pause","next","previous"].includes(op)));
    DHActionsEntityPicker.open({items:model.targets.filter(t=>eligible(t)||existing.some(a=>a.entity_id===t.entity_id)),
      values:existing.map(a=>a.entity_id),renderIcon:targetIcon,renderTest:lightTestControl,onConfirm:ids=>{
        const old=new Set(existing.map(a=>a.entity_id));
        draft.bindings[action]=DHActionsEntityPicker.mergeAssignments(existing,ids,model.targets).map(a=>{
          if(old.has(a.entity_id))return a;
          const t=model.targets.find(t=>t.entity_id===a.entity_id);
          const op=scheduleOperations(a,t)[0]?.[0];
          return {...a,operation:op,data:DHActionsEntityPicker.initialData(op,t)};
        });
        update();renderScheduleEdit();
      }});
  }));
}
function renderSensors(){
  main.replaceChildren();
  main.append(el("p",model.sensor_runtime_ready?"HA события: подключены":"HA события: ожидание подключения","muted"));
  for(const sensor of model.sensors||[]){
    const card=el("article",undefined,"device-card");
    card.tabIndex=0;card.setAttribute("role","button");
    const title=el("strong",(sensor.state==="on"?"● ":sensor.state==="off"?"○ ":"⚠ ")+targetLabel(sensor.entity_id,sensor));
    const info=el("div",[sensor.area,sensor.device_class,sensor.state].filter(Boolean).join(" · "),"muted");
    const targets=el("div",undefined,"bindings");
    for(const a of sensor.config.assignments||[]){
      const line=el("div",undefined,"binding");line.append(targetNode(a.entity_id));
      if(a.when&&a.when!=="always")line.append(el("span",sensorWhenNames[a.when],"muted"));
      if(Object.hasOwn(a,"night_data"))line.append(el("span","Разные параметры День/Ночь","muted"));
      if(a.off_delay_seconds!=null)line.append(el("span","Авто-OFF: "+formatDuration(a.off_delay_seconds),"muted"));
      const due=model.sensor_deadlines?.[a.entity_id];
      if(due!=null)line.append(el("span","До OFF: "+formatDuration(Math.max(0,Math.ceil(due-Date.now()/1000))),"muted"));
      const t=model.targets.find(x=>x.entity_id===a.entity_id);
      if((t?.group||t?.integration==="group")&&!t.sensor_group_supported)line.append(el("span","⚠ Состав группы не подтверждён","problem"));
      targets.append(line);
    }
    if(!targets.children.length)targets.append(el("span","Нет назначений","muted"));
    card.append(title,info,targets);
    card.onclick=()=>openSensor(sensor);
    card.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();openSensor(sensor)}};
    main.append(card);
  }
  if(!(model.sensors||[]).length)main.append(el("p","Нет подтверждённых Motion / Presence датчиков","muted"));
  applyLiveState();
}
function openSensor(sensor){
  editing={...sensor,sensor:true};
  const c=structuredClone(sensor.config);
  draft={id:sensor.entity_id,room:sensor.area,area_id:sensor.area_id,enabled:c.enabled,
         bindings:{presence:c.assignments.map(a=>({...a,data:a.data||{}}))},revision:model.revision,
         disabled_actions:[],lux_entity_id:c.lux_entity_id||(sensor.lux_sources?.length===1?sensor.lux_sources[0].entity_id:undefined),lux_threshold:c.lux_threshold};
  dirty=false;renderSensorEdit();
}
function renderSensorEdit(){
  main.replaceChildren();
  const h=el("div",undefined,"head");
  h.append(button("← Датчики",goBack),el("h2",targetLabel(editing.entity_id,editing)),button("Сохранить",save,"save"));main.append(h);
  main.append(el("p","Автоматическое включение при обнаружении. Таймер запускается после отсутствия.","muted"));
  const enable=el("input");enable.type="checkbox";enable.checked=draft.enabled;enable.onchange=()=>{draft.enabled=enable.checked;update()};
  const l=el("label");l.append(enable,document.createTextNode("Включено"));main.append(l);
  const lux=editing.lux_sources||[];
  if(lux.length||draft.lux_entity_id){
    const p=el("div",undefined,"params");
    const choices=lux.map(x=>[x.entity_id,targetLabel(x.entity_id,x)]);
    if(draft.lux_entity_id&&!choices.some(x=>x[0]===draft.lux_entity_id))choices.push([draft.lux_entity_id,"⚠ "+draft.lux_entity_id]);
    const select=selectOptions([["","Выбрать Lux"],...choices],draft.lux_entity_id||"","Источник Lux");
    // Same-device Lux has no separate enable flag. Choosing a single known source is explicit.
    select.onchange=()=>{draft.lux_entity_id=select.value;update();renderSensorEdit()};
    p.append(select);
    if(draft.lux_entity_id){
      const threshold=el("input");threshold.type="number";threshold.min=0;threshold.max=1000000;threshold.step="any";threshold.value=draft.lux_threshold??"";
      threshold.onchange=()=>{draft.lux_threshold=threshold.value===""?null:Number(threshold.value);update()};
      const label=el("label","Включать при Lux ниже, lx");label.append(threshold);p.append(label);
    }
    main.append(p);
  }
  main.append(el("h2","При обнаружении присутствия"));
  const action="presence",existing=draft.bindings[action]||[];
  for(const a of existing)assignedRow(action,a,main);
  main.append(button(existing.length?"Изменить выбор сущностей":"+ Выбрать сущности",()=>{
    DHActionsEntityPicker.open({items:model.targets.filter(t=>(!t.group&&t.integration!=="group")||t.sensor_group_supported||existing.some(a=>a.entity_id===t.entity_id)),values:existing.map(a=>a.entity_id),domains:["light","switch"],
      areaId:draft.area_id,areaHint:draft.room,renderIcon:targetIcon,renderTest:lightTestControl,
      onConfirm:ids=>{
        draft.bindings[action]=DHActionsEntityPicker.mergeAssignments(existing,ids,model.targets).map(a=>({...a,operation:"on"}));
        if(ids.length)draft.enabled=true;update();renderSensorEdit();
      }});
  }));
}
// Incremental journal feed: no additional HA/MQTT calls, no full catalog reload.
const logPanel=document.querySelector("#log-panel"),logButton=document.querySelector("#toggle-log"),logRows=document.querySelector("#log-rows");
let generation=null,cursor=0,logTimezone=null,logBusy=false,logOpen=false;
let journal=new Map(),logNodes=new Map(),liveStates={},recent=new Map();
function stamp(at){
  try{
    const f=new Intl.DateTimeFormat("en-GB",{timeZone:logTimezone||"UTC",hourCycle:"h23",hour:"2-digit",minute:"2-digit",second:"2-digit",day:"2-digit",month:"2-digit",year:"2-digit"});
    const p=Object.fromEntries(f.formatToParts(new Date(at)).map(x=>[x.type,x.value]));
    return p.hour+":"+p.minute+":"+p.second+" "+p.day+"/"+p.month+"/"+p.year;
  }catch(_){return at}
}
function markIcon(node,state){
  if(!node)return;
  node.classList.toggle("is-on",["on","open","opening","playing","buffering"].includes(state));node.classList.toggle("is-off",["off","closed","closing","idle","paused","standby"].includes(state));
  node.classList.toggle("is-unknown",!knownState(state));
}
function applyLiveState(){
  for(const n of main.querySelectorAll(".binding")){
    const until=recent.get(JSON.stringify([n.dataset.network,n.dataset.device,n.dataset.action]))||0;
    n.classList.toggle("recent",until>Date.now());
  }
  for(const n of main.querySelectorAll(".target")){
    const target=model?.targets.find(t=>t.entity_id===n.dataset.entity);
    const state=target?(liveStates[n.dataset.entity]??target.state):undefined;
    markIcon(n.querySelector(".target-icon"),state);
    const warning=n.querySelector(".problem");
    if(warning)warning.hidden=knownState(state);
    else if(!knownState(state)){const w=el("span","⚠","problem");w.title="Сущность недоступна";n.append(w)}
  }
  for(const wrap of document.querySelectorAll(".light-test"))updateTestControl(wrap);
  for(const [k,v] of recent)if(v<=Date.now())recent.delete(k);
}
function logLightParameters(p){
  const values=[];
  if(p.brightness_pct!=null)values.push("Яркость "+p.brightness_pct+"%");
  if(p.color_temp_kelvin!=null)values.push("CCT "+p.color_temp_kelvin+" K");
  if(Array.isArray(p.rgb_color))values.push("RGB ("+p.rgb_color.join(", ")+")");
  if(Array.isArray(p.xy_color))values.push("XY ("+p.xy_color.join(", ")+")");
  if(Array.isArray(p.hs_color))values.push("HS ("+p.hs_color.join(", ")+")");
  if(p.transition!=null)values.push("переход "+p.transition+" с");
  return values.join(" · ");
}
function renderLogRow(row){
  const n=el("div",undefined,"log-row");
  n.append(el("span",stamp(row.at),"log-time"),el("span",row.device+" · "+row.action+"."));n.title=row.network;
  for(const [eid,t] of Object.entries(row.targets)){
    const item=el("span",undefined,"log-target"),target=model?.targets.find(x=>x.entity_id===eid);
    const ico=targetIcon(target,eid);markIcon(ico,t.observed||t.before);
    const before=(t.before||"?").toUpperCase(),desired=(t.desired||"?").toUpperCase();
    const confirmed=t.status==="confirmed",sent=["sent","confirmed","timeout","superseded","accepted"].includes(t.status);
    const params=logLightParameters(t.parameters||{});
    const change=params&&sent?(before===desired?"":before+" ⇢ "+desired+" · ")+"Запрошено: "+params
      :confirmed?before+" → "+desired:sent?before+" ⇢ "+desired:t.status==="queued"?"…":"пропущено";
    const mark=confirmed?"✓✓":sent?"✓"+(["timeout","superseded"].includes(t.status)?" ⚠":""):t.status==="queued"?"…":"⚠";
    const check=el("span",mark,"log-check "+(confirmed?"":t.status==="sent"?"sent":"problem"));
    check.title={confirmed:"Получено наблюдаемое состояние; не физический ACK",sent:"Команда отправлена, ожидается состояние",accepted:"Команда принята; завершение не подтверждено",timeout:"Нет подтверждения в допустимый срок",superseded:"Заменена более новой командой",queued:"В очереди",skipped:"Пропущено"}[t.status]||"";
    if(target?.group&&confirmed)check.title="Состояние группы Z2M получено; не подтверждение каждого участника (возможен optimistic state)";
    item.title=t.reason||check.title;item.append(ico,el("span",eid.split(".")[1]||eid),el("span",change),check);
    if(t.dispatch_ms!=null)item.append(el("span","Отправка: "+t.dispatch_ms+" мс","muted"));
    if(confirmed){
      const details=t.observed_parameters?logLightParameters(t.observed_parameters):"";
      const duration=t.confirmation_ms!=null?t.confirmation_ms+" мс":"время неизвестно";
      item.append(el("span","Подтверждение: "+duration+(details?" · "+details:""),"muted"));
    }
    if(confirmed&&t.observed_parameters){
      if(target?.group)item.append(el("span","отчёт группы","muted"));
    }
    if(params&&t.status==="accepted")item.append(el("span",t.expected_parameters?"ожидание параметров":"параметры не подтверждены","muted"));
    if(t.status==="skipped"&&t.reason)item.append(el("span",t.reason,"muted"));
    if(["timeout","superseded"].includes(t.status))item.append(el("span",t.reason||(t.status==="timeout"?"Нет подтверждения":"Заменено новой командой"),"muted"));
    n.append(item);
  }
  if(row.reason)n.append(el("span",row.reason,"muted"));
  return n;
}
function renderAllLog(){
  logNodes.clear();logRows.replaceChildren();
  for(const row of [...journal.values()].sort((a,b)=>b.id-a.id)){
    const n=renderLogRow(row);logNodes.set(row.id,n);logRows.append(n);
  }
}
async function pollLog(){
  if(logBusy)return;logBusy=true;
  try{
    const data=await api("log?cursor="+cursor+"&generation="+encodeURIComponent(generation||""));
    const changedZone=data.timezone!==logTimezone;
    logTimezone=data.timezone;liveStates=data.states||{};
    if(data.reset){
      journal.clear();recent.clear();logNodes.clear();logRows.replaceChildren();
      for(const [id,rid] of testRequests)if(rid!==null)testRequests.delete(id);
    }
    generation=data.generation;cursor=data.cursor;
    for(const [id] of journal)if(id<data.oldest){journal.delete(id);logNodes.get(id)?.remove();logNodes.delete(id)}
    for(const row of data.rows){
      const isNew=!journal.has(row.id);
      journal.set(row.id,row);
      if(row.action==="TEST")for(const eid of Object.keys(row.targets))
        if(testRequests.get(eid)===row.id)testRequests.delete(eid);
      if(isNew&&Date.now()-new Date(row.at).getTime()<2000){
        recent.set(JSON.stringify([row.network,row.device,row.action]),new Date(row.at).getTime()+2000)
      }
      if(logOpen&&!changedZone){
        const n=renderLogRow(row),old=logNodes.get(row.id);
        if(old)old.replaceWith(n);else logRows.prepend(n);
        logNodes.set(row.id,n)
      }
    }
    if(logOpen&&changedZone)renderAllLog();
    const mode=({day:"День",night:"Ночь"})[model?.home_mode]||"режим неизвестен";
    const globals=model?.home_profiles_ready?"профили OK":"нет профилей";
    const auto=model?.auto_day_night?"авто ON":"авто OFF";
    document.querySelector("#log-info").textContent=journal.size+" / "+data.limit+" · "+(logTimezone||"UTC (HA timezone недоступен)")+" · "+mode+" · "+globals+" · "+auto+" · "+(data.storage_error?"SQLite ⚠ RAM":data.storage==="sqlite"?"SQLite":"RAM");
    applyLiveState();
  }catch(e){document.querySelector("#log-info").textContent="Нет связи: "+e.message}
  finally{logBusy=false}
}
logButton.onclick=()=>{
  logOpen=!logOpen;logPanel.hidden=!logOpen;
  logButton.classList.toggle("active",logOpen);logButton.setAttribute("aria-expanded",String(logOpen));
  document.querySelector("#workspace").classList.toggle("log-open",logOpen);
  if(logOpen){renderAllLog();pollLog()}
};
document.querySelector("#export-log").onclick=async()=>{
  try{
    const doc=await api("log/export"),blob=new Blob([JSON.stringify(doc,null,2)],{type:"application/json"});
    const url=URL.createObjectURL(blob),a=el("a");
    a.href=url;a.download="dh-actions-log-"+new Date().toISOString().replace(/[:.]/g,"-")+".json";
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);
  }catch(e){document.querySelector("#log-info").textContent="Ошибка выгрузки: "+e.message}
};
const jsonDialog=document.querySelector("#json-dialog"),jsonText=document.querySelector("#json-text"),jsonStatus=document.querySelector("#json-status");
async function showJSON(){
  const doc=await api("bindings");jsonText.value=JSON.stringify(doc,null,2);jsonStatus.textContent="";jsonDialog.showModal();return doc;
}
document.querySelector("#view-json").onclick=async()=>{try{await showJSON()}catch(e){notice.textContent=e.message}};
document.querySelector("#json-close").onclick=()=>jsonDialog.close();
document.querySelector("#json-copy").onclick=async()=>{
  try{await navigator.clipboard.writeText(jsonText.value);jsonStatus.textContent="Скопировано"}
  catch(_){jsonText.focus();jsonText.select();jsonStatus.textContent="Нажмите Ctrl+C / Cmd+C"}
};
document.querySelector("#export").onclick=async()=>{
  try{const doc=await api("bindings"),blob=new Blob([JSON.stringify(doc,null,2)],{type:"application/json"});
    const url=URL.createObjectURL(blob),a=el("a");
    a.href=url;a.download="dh-actions-bindings-"+new Date().toISOString().slice(0,10)+".json";document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),10000);
    notice.textContent="JSON подготовлен. Если Ingress блокирует скачивание, используйте JSON / Копировать.";
  }catch(e){notice.textContent=e.message}
};
const fileInput=document.querySelector("#import-file");
document.querySelector("#import").onclick=()=>{
  if(dirty){notice.textContent="Сначала сохраните или отмените изменения устройства.";return}
  fileInput.click()
};
fileInput.onchange=async()=>{
  const file=fileInput.files[0];fileInput.value="";if(!file)return;
  try{
    if(file.size>1048576)throw Error("JSON превышает 1 MiB");
    const documentText=await file.text();
    JSON.parse(documentText); // Local syntax check; preserve original keys for server validation.
    if(!confirm("Заменить текущие привязки содержимым "+file.name+"?"))return;
    await api("import",'{"revision":'+JSON.stringify(model.revision)+',"document":'+documentText+'}',true);
    editing=null;draft=null;dirty=false;await load();notice.textContent="Привязки загружены.";
  }catch(e){notice.textContent=e.message;notice.classList.add("error")}
};
load();pollLog();setInterval(load,5000);setInterval(pollLog,1000);
