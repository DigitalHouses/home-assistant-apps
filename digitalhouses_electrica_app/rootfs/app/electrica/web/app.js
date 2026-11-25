"use strict";
let model, editing=null, draft=null, dirty=false, showSwitch=false, busy=false;
const main=document.querySelector("#main"), notice=document.querySelector("#notice"), scan=document.querySelector("#scan");
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function button(text,fn,cls){const n=el("button",text,cls);n.onclick=fn;return n}
function icon(t,id){
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
  if(kind==="switch"){path("M7 7h10a5 5 0 0 1 0 10H7A5 5 0 0 1 7 7Z");circle(7,12,2.5)}
  else if(kind==="group"){path("M4 11a4 4 0 1 1 8 0c0 2-2 3-2 5H6c0-2-2-3-2-5ZM6 19h4M12 5a4 4 0 0 1 8 0c0 2-2 3-2 5h-4m0 3h4")}
  else if(kind==="dimmer"){circle(12,12,4);path("M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5")}
  else{path("M9 18h6m-5 3h4M9 15c0-2-4-4-4-8a7 7 0 0 1 14 0c0 4-4 6-4 8Z");
    if(kind==="rgb"){circle(9,7,2,"#ef7474");circle(15,7,2,"#82efc7");circle(12,11,2,"#8baaff")}
    if(kind==="cct"){path("M12 4v8");circle(9,8,1.5,"#ffd094");circle(15,8,1.5,"#e9f0f7")}
  }
  n.append(svg);return n;
}
function stat(d){return {same:["●",""],disabled:["Ⅱ","muted"],missing:["✖","danger"],offline:["⚠","problem"],unknown:["?","muted"]}[d.status]||["⚠","problem"]}
function targetNode(id){const t=model.targets.find(x=>x.entity_id===id);const n=el("span",undefined,"target");n.dataset.entity=id;n.append(targetIcon(t,id),el("span",id.split(".")[1]||id));if(!t||!["on","off"].includes(t.state)){const w=el("span","⚠","problem");w.title=t?"Сущность недоступна":"Сущность не найдена";n.append(w)}return n}
async function api(path,data,raw=false){const r=await fetch("api/"+path,data===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:raw?data:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error||"Ошибка");return v}
async function load(){try{model=await api("state");document.querySelector("#app-version").textContent="v"+model.version;document.querySelector("#summary").textContent="Устройства ("+model.devices.length+") · Сети Z2M ("+new Set(model.devices.map(d=>d.network).filter(n=>n!=="—")).size+")";notice.classList.toggle("error",!!model.scan.error);scan.disabled=model.scan.state==="updating"||busy;scan.textContent=model.scan.state==="updating"?"Сканирование…":"⟳ Сканировать";if(!editing)renderList();if(!editing&&!busy){if(model.scan.error)notice.textContent=model.scan.error;else if(model.scan.state==="updating")notice.textContent="Сканирование…";else if(model.report){const p=model.report.problems||[];notice.textContent="Последний Scan: "+(model.report.scanned??0)+" устройств · "+p.length+" проблем";notice.title=p.map(x=>x.name+": "+x.reason).join("\n")}}}catch(e){notice.textContent=e.message}}
function renderList(){main.replaceChildren();for(const d of model.devices){const a=el("article"),h=el("div",undefined,"head"),info=el("div",undefined,"device-info"),[sym,cls]=stat(d),status=el("span",sym+" ", "status "+cls);status.title=d.reason||d.status;const name=el("strong",undefined,"device-name");name.append(status,document.createTextNode(d.name));info.append(name,el("div",d.model+" · "+d.room+" · "+d.network,"muted"));const gear=button("⚙",()=>open(d),"settings");gear.title="Настроить "+d.name;gear.setAttribute("aria-label",gear.title);h.append(info,gear);a.append(h);const b=el("div",undefined,"bindings");for(const [action,targets] of Object.entries(d.bindings)){const x=el("span",undefined,"binding");x.dataset.device=d.name;x.dataset.network=d.network;x.dataset.action=action;x.append(el("span",action+" →"));for(const t of targets)x.append(targetNode(t.entity_id));if(d.disabled_actions?.includes(action))x.append(el("span","Ⅱ","muted"));if(!d.actions.includes(action))x.append(el("span","⚠","problem"));b.append(x)}if(!b.children.length)b.append(el("span","Нет привязок","muted"));a.append(b);main.append(a)}applyLiveState()}
function open(d){editing=d;draft=structuredClone(d);draft.disabled_actions??=[];draft.revision=model.revision;dirty=false;showSwitch=false;renderEdit()}
function goBack(){if(dirty&&!confirm("Отменить несохранённые изменения?"))return;editing=null;draft=null;dirty=false;renderList();load()}
function update(){dirty=true}
function addParam(parent,t,a,key,label,min,max,step){const wrap=el("label"),check=el("input");check.type="checkbox";check.checked=Object.hasOwn(a.data,key);const input=el("input");input.type="number";input.min=min;input.max=max;input.step=step;input.value=a.data[key]??min;input.disabled=!check.checked;check.onchange=()=>{if(check.checked)a.data[key]=Number(input.value);else delete a.data[key];input.disabled=!check.checked;update();if(key==="color_temp_kelvin")renderEdit()};input.onchange=()=>{a.data[key]=Number(input.value);update()};wrap.append(check,document.createTextNode(label),input);parent.append(wrap)}
function assignedRow(action,a,container){const t=model.targets.find(t=>t.entity_id===a.entity_id),row=el("div",undefined,"assigned");row.append(targetIcon(t,a.entity_id),el("strong",(t?.name||a.entity_id)+" · "+a.entity_id));const op=el("select");for(const [v,n] of [["toggle","Toggle"],["on","ON"],["off","OFF"]]){const o=el("option",n);o.value=v;op.append(o)}op.value=a.operation;op.onchange=()=>{a.operation=op.value;if(op.value==="off")for(const k of Object.keys(a.data))if(k!=="transition")delete a.data[k];update();renderEdit(action)};row.append(op,button("Удалить",()=>{draft.bindings[action]=draft.bindings[action].filter(x=>x.entity_id!==a.entity_id);if(!draft.bindings[action].length){delete draft.bindings[action];draft.disabled_actions=draft.disabled_actions.filter(x=>x!==action)}update();renderEdit(action)}));if(!t){row.append(el("span","⚠ Сущность отсутствует","problem"));container.append(row);return}if(a.entity_id.startsWith("light.")){const p=el("div",undefined,"params");if(a.operation!=="off"){if(t.brightness)addParam(p,t,a,"brightness_pct","Яркость %",0,100,1);if(t.cct&&Number.isInteger(t.min_kelvin)&&Number.isInteger(t.max_kelvin)&&!Object.hasOwn(a.data,"rgb_color"))addParam(p,t,a,"color_temp_kelvin","Kelvin",t.min_kelvin,t.max_kelvin,1);if(t.rgb&&!Object.hasOwn(a.data,"color_temp_kelvin")){const l=el("label"),c=el("input"),picker=el("input");c.type="checkbox";c.checked=Object.hasOwn(a.data,"rgb_color");picker.type="color";picker.value="#"+(a.data.rgb_color||[255,255,255]).map(v=>v.toString(16).padStart(2,"0")).join("");picker.disabled=!c.checked;c.onchange=()=>{if(c.checked)a.data.rgb_color=[1,3,5].map(i=>parseInt(picker.value.slice(i,i+2),16));else delete a.data.rgb_color;update();renderEdit(action)};picker.oninput=()=>{a.data.rgb_color=[1,3,5].map(i=>parseInt(picker.value.slice(i,i+2),16));update()};l.append(c,document.createTextNode("RGB"),picker);p.append(l)}}if(t.transition)addParam(p,t,a,"transition","Transition, сек",0,60,.1);row.append(p)}container.append(row)}
function actionGroup(action){const p=action.match(/_(left|right|center|plus|minus|both|[0-9]+)$/)||action.match(/^(button_[0-9]+)_/);return p?p[1]:"Нажатия"}
function renderEdit(expand){main.replaceChildren();const h=el("div",undefined,"head");h.append(button("← Устройства",goBack),el("h2",draft.name+" · "+draft.room),button("Сохранить",save,"save"));main.append(h);const enabled=el("input");enabled.type="checkbox";enabled.checked=draft.enabled;enabled.onchange=()=>{draft.enabled=enabled.checked;update()};const l=el("label");l.append(enabled,document.createTextNode("Включено"));const controls=el("div",undefined,"editor-controls");controls.append(l);const sw=el("input");sw.type="checkbox";sw.checked=showSwitch;sw.onchange=()=>{showSwitch=sw.checked;renderEdit(expand)};const sl=el("label");sl.append(sw,document.createTextNode("Показать switch.*"));controls.append(sl);main.append(controls);let group=null;const ordered=[...new Set([...draft.actions,...Object.keys(draft.bindings)])].sort((a,b)=>actionGroup(a).localeCompare(actionGroup(b))||a.localeCompare(b));for(const action of ordered){const next=actionGroup(action);if(next!==group){main.append(el("h2",next==="Нажатия"?next:"Клавиша "+next));group=next;}const allowed=draft.actions.includes(action),detail=el("details",undefined,"action");detail.open=action===expand||(!expand&&!!draft.bindings[action]);detail.append(el("summary",action+" · "+(draft.bindings[action]||[]).map(a=>a.entity_id.split(".")[1]).join(", ")+(allowed?"":" ⚠")));if(draft.bindings[action]){const c=el("input");c.type="checkbox";c.checked=!draft.disabled_actions.includes(action);c.onchange=()=>{draft.disabled_actions=c.checked?draft.disabled_actions.filter(x=>x!==action):[...draft.disabled_actions,action];update()};const l=el("label");l.append(c,document.createTextNode("Назначение активно"));detail.append(l)}for(const a of draft.bindings[action]||[])assignedRow(action,a,detail);if(allowed){const search=el("input");search.placeholder="Поиск светильников / реле";search.className="search";const results=el("div",undefined,"addlist");const fill=()=>{results.replaceChildren();for(const t of model.targets.filter(t=>(t.entity_id.startsWith("light.")||showSwitch)&&!(draft.bindings[action]||[]).some(a=>a.entity_id===t.entity_id)&&[t.name,t.entity_id,t.area].join(" ").toLowerCase().includes(search.value.toLowerCase()))){const b=button("",()=>{(draft.bindings[action]??=[]).push({entity_id:t.entity_id,operation:"toggle",data:{}});draft.enabled=true;update();renderEdit(action)});b.append(targetIcon(t,t.entity_id),document.createTextNode(t.name+" · "+t.area));b.title=t.entity_id;results.append(b)}};search.oninput=fill;fill();detail.append(search,results)}main.append(detail)}}
async function save(){try{await api("save",{id:draft.id,revision:draft.revision,enabled:draft.enabled,bindings:draft.bindings,disabled_actions:draft.disabled_actions});dirty=false;editing=null;notice.textContent="Сохранено";await load()}catch(e){notice.textContent=e.message}}
scan.onclick=async()=>{busy=true;scan.disabled=true;try{await api("scan",{});notice.textContent="Сканирование запущено"}catch(e){notice.textContent=e.message}finally{busy=false;await load()}};
document.querySelector("#devices-nav").onclick=()=>{if(editing)goBack()};
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
  node.classList.toggle("is-on",state==="on");node.classList.toggle("is-off",state==="off");
  node.classList.toggle("is-unknown",!["on","off"].includes(state));
}
function applyLiveState(){
  for(const n of main.querySelectorAll(".binding")){
    const until=recent.get(JSON.stringify([n.dataset.network,n.dataset.device,n.dataset.action]))||0;
    n.classList.toggle("recent",until>Date.now());
  }
  for(const n of main.querySelectorAll(".target")){
    const state=liveStates[n.dataset.entity]??model?.targets.find(t=>t.entity_id===n.dataset.entity)?.state;
    markIcon(n.querySelector(".target-icon"),state);
    const warning=n.querySelector(".problem");
    if(warning)warning.hidden=["on","off"].includes(state);
    else if(!["on","off"].includes(state)){const w=el("span","⚠","problem");w.title="Сущность недоступна";n.append(w)}
  }
  for(const [k,v] of recent)if(v<=Date.now())recent.delete(k);
}
function renderLogRow(row){
  const n=el("div",undefined,"log-row");
  n.append(el("span",stamp(row.at),"log-time"),el("span",row.device+" · "+row.action+"."));n.title=row.network;
  for(const [eid,t] of Object.entries(row.targets)){
    const item=el("span",undefined,"log-target"),target=model?.targets.find(x=>x.entity_id===eid);
    const ico=targetIcon(target,eid);markIcon(ico,t.observed||t.before);
    const before=(t.before||"?").toUpperCase(),desired=(t.desired||"?").toUpperCase();
    const confirmed=t.status==="confirmed",sent=["sent","confirmed","timeout","superseded"].includes(t.status);
    const change=confirmed?before+" → "+desired:sent?before+" ⇢ "+desired:t.status==="queued"?"…":"пропущено";
    const mark=confirmed?"✓✓":sent?"✓"+(["timeout","superseded"].includes(t.status)?" ⚠":""):t.status==="queued"?"…":"⚠";
    const check=el("span",mark,"log-check "+(confirmed?"":t.status==="sent"?"sent":"problem"));
    check.title={confirmed:"Получено наблюдаемое состояние; не физический ACK",sent:"Команда отправлена, ожидается состояние",timeout:"Нет подтверждения за 90 сек.",superseded:"Заменена более новой командой",queued:"В очереди",skipped:"Пропущено"}[t.status]||"";
    if(target?.group&&confirmed)check.title="Состояние группы Z2M получено; не подтверждение каждого участника (возможен optimistic state)";
    item.title=t.reason||check.title;item.append(ico,el("span",eid.split(".")[1]||eid),el("span",change),check);n.append(item);
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
    if(data.reset){journal.clear();recent.clear();logNodes.clear();logRows.replaceChildren()}
    generation=data.generation;cursor=data.cursor;
    for(const [id] of journal)if(id<data.oldest){journal.delete(id);logNodes.get(id)?.remove();logNodes.delete(id)}
    for(const row of data.rows){
      const isNew=!journal.has(row.id);
      journal.set(row.id,row);
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
    document.querySelector("#log-info").textContent=journal.size+" / "+data.limit+" · "+(logTimezone||"UTC (HA timezone недоступен)");
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
    a.href=url;a.download="dh-electrica-bindings-"+new Date().toISOString().slice(0,10)+".json";document.body.append(a);a.click();a.remove();
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
