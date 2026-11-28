"use strict";
const PRODUCT="DigitalHouses/digitalhouses_system_globals_app", GLOBAL="DigitalHouses/Global/night_mode";
const $=id=>document.getElementById(id);
let latest, baseline={}, pending=false, stateRequest=0;
const dirty=new Set(), edits=new Map();
function markDirty(id){dirty.add(id);edits.set(id,(edits.get(id)||0)+1)}
const numeric={brightness:"Яркость света, %",volume:"Громкость, %",transition_seconds:"Плавный переход, с"};
const flags={voice_notifications_enabled:"Голосовые уведомления",noncritical_sound_notifications_enabled:"Некритические звуки"};
const esc=s=>String(s);
function option(v,t){const o=document.createElement("option");o.value=v;o.textContent=t;return o}
function field(form,label,name,type,attrs={}){const l=document.createElement("label");l.textContent=label;const i=document.createElement(type==="select"?"select":"input");i.name=name;if(type!=="select")i.type=type;for(const[k,v]of Object.entries(attrs))i.setAttribute(k,v);l.append(i);form.append(l);return i}
function bool(form,name,label){const el=field(form,label,name,"select");for(const [v,t] of [["","Не задано"],["true","Вкл."],["false","Выкл."]])el.append(option(v,t))}
function makeProfile(mode){const f=document.createElement("form");f.id=mode+"Form";const h=document.createElement("h3");h.textContent=mode==="day"?"Дневной профиль":"Ночной профиль";f.append(h);
for(const[k,l]of Object.entries(numeric))field(f,l,k,"number",{min:"0",step:k==="transition_seconds"?"any":"1",...(k==="transition_seconds"?{}:{max:"100"})});
const c=field(f,"Температура, K","color_temp_kelvin","number",{min:"2000",max:"6000",step:"1"});const picker=field(f,"RGB — выбрать цвет","picker","color");
const rgb=document.createElement("input");rgb.type="hidden";rgb.name="rgb_color";f.append(rgb);
const clear=document.createElement("button");clear.type="button";clear.textContent="Сбросить RGB";clear.setAttribute("aria-label","Очистить RGB профиля");const colorLabel=picker.parentElement;const colorRow=document.createElement("div");colorRow.style.cssText="display:grid;grid-template-columns:1fr minmax(100px,150px);gap:8px;align-items:center;margin:8px 0";colorLabel.replaceWith(colorRow);colorLabel.textContent="RGB — выбрать цвет";colorLabel.style.display="block";colorLabel.htmlFor=picker.id=f.id+"Rgb";const colorControls=document.createElement("div");colorControls.style.cssText="display:flex;align-items:center;gap:6px;min-width:0";picker.style.minWidth="0";clear.style.flexShrink="0";colorControls.append(picker,clear);colorRow.append(colorLabel,colorControls);
function colorStatus(){picker.setAttribute("aria-label",rgb.value?"Выбрать цвет RGB":"RGB не задан");clear.disabled=!rgb.value;picker.style.opacity=rgb.value?"1":".5";clear.textContent=rgb.value?"×":"—";clear.title=rgb.value?"Сбросить RGB":"RGB не задан"}
function chooseColor(){rgb.value=picker.value;markDirty(f.id);colorStatus()}
picker.addEventListener("input",chooseColor);picker.addEventListener("change",chooseColor);
clear.addEventListener("click",()=>{rgb.value="";picker.value="#000000";markDirty(f.id);colorStatus()});
f.colorStatus=colorStatus;colorStatus();
for(const[k,l]of Object.entries(flags))bool(f,k,l);const b=document.createElement("button");b.className="primary";b.textContent="Сохранить";f.append(b);$("profiles").append(f);
f.addEventListener("input",()=>markDirty(f.id));f.addEventListener("change",()=>markDirty(f.id));f.addEventListener("submit",e=>{e.preventDefault();const value={};for(const k of Object.keys(numeric))value[k]=f.elements[k].value===""?null:Number(f.elements[k].value);for(const k of Object.keys(flags))value[k]=f.elements[k].value===""?null:f.elements[k].value==="true";value.color_temp_kelvin=c.value===""?null:Number(c.value);value.rgb_color=rgb.value===""?null:[1,3,5].map(i=>parseInt(rgb.value.slice(i,i+2),16));
const patch={};for(const k of [...Object.keys(numeric),...Object.keys(flags),"color_temp_kelvin","rgb_color"])if(JSON.stringify(value[k])!==JSON.stringify(baseline[f.id]?.[k]))patch[k]=value[k];send(PRODUCT+"/profiles/set",{[mode]:patch},f.id)});
}
makeProfile("day");makeProfile("night");
function populate(f,values){if(dirty.has(f.id))return;baseline[f.id]=structuredClone(values);for(const[k,v]of Object.entries(values)){const e=f.elements[k];if(!e)continue;e.value=k==="rgb_color"&&v?"#"+v.map(n=>n.toString(16).padStart(2,"0")).join(""):v===null?"":String(v)}if(f.elements.picker){f.elements.picker.value=f.elements.rgb_color.value||"#000000";f.colorStatus()}}
function render(v){latest=v;renderChrome(v);$("mode").textContent=({on:"Ночь",off:"День"})[v.state.night_mode]||"Не задано";$("card").textContent=v.card.state+(v.card.operation?" · "+v.card.operation:"")+(v.card.error?" · "+v.card.error:"");populate($("config"),v.state.config);for(const m of ["day","night"])populate($(m+"Form"),v.state.profiles[m]);$("gates").replaceChildren();for(const[k,ready]of Object.entries(v.gates)){const p=document.createElement("p");p.className=ready?"good":"bad";const d=v.diagnostics[k];p.textContent=k+": "+(ready?"ON":"OFF")+(d?" · "+d.reason+(d.required?"":" (необязательный)"):"");$("gates").append(p)}for(const[base,b]of Object.entries(v.zigbee_bridges||{})){const p=document.createElement("p");p.className=b.ready?"good":"bad";p.textContent="Z2M · "+base+": "+(b.ready?"ON":"OFF");$("gates").append(p)}$("lifecycle").textContent=JSON.stringify(v.lifecycle,null,2)}
async function poll(){if(document.hidden)return;const request=++stateRequest;try{const r=await fetch("./api/state",{cache:"no-store"});if(!r.ok)throw Error("HTTP "+r.status);const v=await r.json();if(request===stateRequest&&!pending)render(v)}catch(e){if(request===stateRequest&&!pending){$("card").textContent="Связь с App потеряна";shell.setStatuses(unknownStatuses);settings.setValue("telemetry","Неизвестно")}}}
async function send(topic,payload,form){if(pending)return;pending=true;const editVersion=edits.get(form);setBusy(true);try{const r=await fetch("./api/command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({topic,payload})});const v=await r.json();if(!r.ok)throw Error(v.error||"HTTP "+r.status);if(form){if(edits.get(form)===editVersion)dirty.delete(form);else baseline[form]=structuredClone(form==="config"?v.state.config:v.state.profiles[form==="dayForm"?"day":"night"]);}++stateRequest;render(v);$("result").textContent="Команда принята"}catch(e){$("result").textContent=e.message}finally{pending=false;setBusy(false)}}
$("config").addEventListener("input",()=>markDirty("config"));$("config").addEventListener("change",()=>markDirty("config"));
$("config").addEventListener("submit",e=>{e.preventDefault();const v={};for(const k of ["night_start","night_end","timezone"])v[k]=e.target.elements[k].value||null;const a=e.target.elements.auto_switch.value;v.auto_switch=a===""?null:a==="true";const p={};for(const k in v)if(v[k]!==baseline.config?.[k])p[k]=v[k];send(PRODUCT+"/config/set",p,"config")});
$("day").onclick=()=>send(GLOBAL+"/set","off");$("night").onclick=()=>send(GLOBAL+"/set","on");
function exportConfig(){if(!latest)return;const blob=new Blob([JSON.stringify(latest.state,null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="dh-system-globals.json";a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};

$("file").onchange=async()=>{try{const f=$("file").files[0];if(!f)return;if(f.size>65536)throw Error("Файл слишком большой");const v=JSON.parse(await f.text());if(!v.profiles||!v.config)throw Error("Некорректный файл");await send("internal/import",{night_mode:v.night_mode,config:v.config,profiles:v.profiles})}catch(e){$("result").textContent=e.message}finally{$("file").value=""}};

// The shell and common settings mount once. Navigation hides, never rebuilds, the forms.
const unknownStatuses={ha:"unknown",mqtt:"unknown",sync:"unknown",telemetry:"unknown"};
const shell=DHLibUI.mount({target:$("chrome"),title:"DigitalHouses System Globals",language:"ru",
  items:[{id:"overview",label:"Главная"},{id:"settings",label:"Настройки"},{id:"log",label:"LOG",href:"./log"}],
  active:"overview",statuses:unknownStatuses,onRefresh:()=>send(PRODUCT+"/control/refresh","PRESS"),
  onNavigate:id=>{$("overview").hidden=id!=="overview";$("settings-page").hidden=id!=="settings";shell.setActive(id)}
});
const theme=document.createElement("select");theme.setAttribute("aria-label","Тема");
for(const [v,t] of [["auto","Системная"],["light","Светлая"],["dark","Тёмная"]])theme.append(option(v,t));
const themeKey="dh-system-globals-ui-theme";
try{theme.value=localStorage.getItem(themeKey)||"auto"}catch{theme.value="auto"}
if(!theme.value)theme.value="auto";
DHLibUI.setTheme(theme.value);
theme.addEventListener("change",()=>{DHLibUI.setTheme(theme.value);try{localStorage.setItem(themeKey,theme.value)}catch{}});
const toastTarget=$("toast-settings");toastTarget.hidden=false;
const settings=DHLibUI.mountSettings({target:$("app-settings"),language:"ru",sections:[
  {id:"app",rows:[{id:"version"},{id:"latest"},{id:"timezone"}],actions:[{id:"check",onClick:()=>send(PRODUCT+"/control/check_updates","PRESS")}]},
  {id:"interface",rows:[{id:"theme",control:theme},{id:"toast",control:toastTarget}]},
  {id:"config",actions:[{id:"import",onClick:()=>$("file").click()},{id:"export",onClick:exportConfig}]},
  {id:"diagnostics",rows:[{id:"telemetry"},{id:"debug"}]}
]});
function gateStatus(v,key){const state=v.gates?.[key];const reason=v.diagnostics?.[key]?.reason;
  if(state===true)return "ok";if(state!==false)return "unknown";
  return reason==="awaiting_probe"?"unknown":"error";
}
function hasUpdate(v){
  if(!v.latest_version||!v.version)return false;
  const a=v.latest_version.split(".").map(Number), b=v.version.split(".").map(Number);
  for(let i=0;i<3;i++){if(a[i]>b[i])return true;if(a[i]<b[i])return false}return false;
}
function renderChrome(v){
  const telemetry=v.telemetry_status||"unknown";
  const states={ha:gateStatus(v,"ha_ready"),mqtt:v.mqtt_connected===false?"error":gateStatus(v,"mqtt_ready"),sync:"unknown",telemetry};
  shell.setStatuses(states);shell.setVersion(v.version,hasUpdate(v)?v.latest_version:undefined);
  settings.setValue("version",v.version||"—");settings.setValue("latest",v.latest_version||"—");
  settings.setValue("timezone",v.ha_timezone||"UTC (временно)");
  settings.setValue("telemetry",({ok:"OK · отправлено",warning:"Ошибка последней отправки",disabled:"Отключено",unknown:"Неизвестно"})[telemetry]||"Неизвестно");
  settings.setValue("debug",v.journal_debug===true?"Вкл.":v.journal_debug===false?"Выкл.":"—");
  setBusy(pending);
}
function setBusy(value){
  const operation=latest?.card?.state==="running";
  const disconnected=latest?.mqtt_connected===false;
  shell.setRefreshDisabled(value||operation||disconnected);
  settings.setDisabled("check",value||operation||disconnected);
  settings.setDisabled("import",value);
  settings.setDisabled("export",!latest);
}
setBusy(false);
document.querySelector(".dh-lib-ui-nav-log").addEventListener("click",e=>{
  if(dirty.size&&!confirm("Есть несохранённые изменения. Открыть журнал без сохранения?"))e.preventDefault();
});
if(globalThis.DHLibJournalToast)DHLibJournalToast.mount({product:"digitalhouses_system_globals_app",language:"ru",settingsTarget:$("toast-settings"),onEvents:()=>poll()});
else toastTarget.textContent="Журнал недоступен";
poll();setInterval(poll,3000);
