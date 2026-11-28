"use strict";
const $=id=>document.getElementById(id), rows=$("rows");
const labels={
 ru:{back:"← Приложение",close:"Закрыть журнал",export:"Выгрузить .log",clear:"Очистить",search:"Поиск по журналу",follow:"Автопрокрутка",all:"Все уровни",confirm:"Очистить весь журнал?",unavailable:"SQLite недоступна. Журналирование остановлено до перезапуска приложения.",rejected:"Отклонено записей",clearUnavailable:"Очистка невозможна без SQLite. История сохранена.",lost:"Нет связи с приложением",copy:"Копировать",details:"Подробности",empty:"Нет записей",copied:"Скопировано",failed:"Не удалось выполнить операцию"},
 en:{back:"← App",close:"Close journal",export:"Download .log",clear:"Clear",search:"Search journal",follow:"Auto-scroll",all:"All levels",confirm:"Clear the entire journal?",unavailable:"SQLite unavailable. Logging suspended until App restart.",rejected:"Rejected entries",clearUnavailable:"Cannot clear without SQLite. History retained.",lost:"App connection lost",copy:"Copy",details:"Details",empty:"No entries",copied:"Copied",failed:"Operation failed"}
};
const levels=["debug","info","success","pending","warning","error","lifecycle"];
let lang="ru",generation=null,cursor=0,epoch=0,busy=false,entries=new Map(),status="",storage="sqlite",product="";
try{lang=localStorage.getItem("dh-journal-language")==="en"?"en":"ru"}catch{}
const requestedLanguage=new URLSearchParams(location.search).get("lang");
const sharedLanguage=requestedLanguage==="ru"||requestedLanguage==="en";
let languageChanged=false,productId="";
if(requestedLanguage!==null)lang=requestedLanguage==="ru"?"ru":"en";
function persistLanguage(){
 try{
  localStorage.setItem("dh-journal-language",lang);
  if(sharedLanguage&&productId)localStorage.setItem("dh-lib-ui-language:"+productId,lang);
 }catch{}
}
$("language").value=lang;
function tr(){return labels[lang]}
function localize(){
 document.documentElement.lang=lang;
 for(const k of ["back","export","clear"])$(k).textContent=tr()[k];
 const close=$("dh-lib-journal-close");if(close){close.title=tr().close;close.setAttribute("aria-label",tr().close)}
 $("search").placeholder=tr().search;$("level").setAttribute("aria-label",tr().all);$("language").setAttribute("aria-label",lang==="ru"?"Язык":"Language");$("follow-label").textContent=tr().follow;
 const old=$("level").value||"";$("level").replaceChildren();
 for(const k of ["",...levels]){const o=document.createElement("option");o.value=k;o.textContent=k?(lang==="ru"?({debug:"Отладка",info:"Информация",success:"Успех",pending:"Ожидание",warning:"Предупреждение",error:"Ошибка",lifecycle:"Запуск / остановка"})[k]:k.toUpperCase()):tr().all;$("level").append(o)}
 $("level").value=old;
}
function filter(){
 const q=$("search").value.toLocaleLowerCase(),level=$("level").value;
 let n=0;for(const {row,node} of entries.values()){node.hidden=Boolean((level&&row.level!==level)||(q&&!node.dataset.search.includes(q)));if(!node.hidden)n++}
 $("footer").textContent=n+" / "+entries.size+(n?"":" · "+tr().empty);
}
function add(row,fragment){
 const node=document.createElement("div");node.className="entry "+row.level;
 const t=document.createElement("span");t.className="time";t.textContent=row.local_time;
 const m=document.createElement("span");m.textContent=(row.icon||"")+" "+row.message;
 const copy=document.createElement("button");copy.type="button";copy.textContent="⧉";copy.title=tr().copy;copy.setAttribute("aria-label",tr().copy);
 copy.onclick=async()=>{try{const value=t.textContent+" "+m.textContent;if(navigator.clipboard){await navigator.clipboard.writeText(value)}else{const input=document.createElement("textarea");input.value=value;document.body.append(input);input.select();const ok=document.execCommand("copy");input.remove();if(!ok)throw Error()}$("status").textContent=tr().copied}catch{$("status").textContent=tr().failed}};
 node.dataset.search=(t.textContent+" "+m.textContent+" "+row.code+" "+JSON.stringify(row.params)).toLocaleLowerCase();
 const content=document.createElement("div");content.append(m);if(Object.keys(row.params).length){const d=document.createElement("details"),summary=document.createElement("summary"),pre=document.createElement("pre");summary.textContent=tr().details;summary.setAttribute("aria-label",tr().details);d.addEventListener("toggle",()=>{if(d.open&&!pre.textContent)pre.textContent=JSON.stringify(row.params,null,2)});d.append(summary,pre);content.append(d)}node.append(t,content,copy);fragment.append(node);entries.set(row.id,{row,node});
}
function reset(){entries.clear();rows.replaceChildren();generation=null;cursor=0}
async function poll(){
 if(busy||document.hidden)return;
 busy=true;const current=epoch;
 try{
 const params=new URLSearchParams({lang,after:String(cursor),generation:generation||""});
 const r=await fetch("./api/log?"+params,{cache:"no-store"});if(!r.ok)throw Error("HTTP");
 const d=await r.json();if(current!==epoch)return;
 const follow=$("follow").checked;let changed=false;
 if(generation!==d.generation){reset();generation=d.generation;changed=true}
 for(const [id,e] of entries)if(id<d.oldest||!d.count){e.node.remove();entries.delete(id);changed=true}
 if(d.rows.length){const fragment=document.createDocumentFragment();for(const row of d.rows)if(!entries.has(row.id)){add(row,fragment);changed=true}rows.append(fragment)}
 cursor=d.newest;storage=d.storage;product=d.product_name||d.product;productId=d.product;
 if(languageChanged){persistLanguage();languageChanged=false}
 $("product").textContent=product+(d.app_version?" v"+d.app_version:"");document.title=product+" · LOG";$("count").textContent=(d.count??"—")+" / "+d.limit;
 status=[d.timezone?(d.timezone_fallback?(lang==="ru"?"UTC (временно: часовой пояс HA неизвестен)":"UTC (temporary: HA timezone unavailable)"):d.timezone):"",storage==="unavailable"?tr().unavailable:"",d.rejected?tr().rejected+": "+d.rejected:""].filter(Boolean).join(" · ");$("status").textContent=status;$("clear").disabled=!d.can_clear;$("export").disabled=storage!=="sqlite";
 if(changed)filter();if(storage!=="sqlite")$("footer").textContent=tr().unavailable;if(follow&&changed){rows.scrollTop=rows.scrollHeight;$("follow").checked=true}
 }catch{$("status").textContent=tr().lost}finally{busy=false;if(current!==epoch)poll()}
}
$("language").onchange=()=>{lang=$("language").value;languageChanged=true;persistLanguage();epoch++;localize();reset();poll()};
$("search").oninput=filter;$("level").onchange=filter;
$("follow").onchange=()=>{if($("follow").checked)rows.scrollTop=rows.scrollHeight};
rows.addEventListener("scroll",()=>{if(rows.scrollHeight-rows.scrollTop-rows.clientHeight>40)$("follow").checked=false});
$("export").onclick=()=>{const a=document.createElement("a");a.href="./api/log/export?lang="+lang;a.click()};
$("clear").onclick=async()=>{if(!confirm(tr().confirm))return;try{const r=await fetch("./api/log/clear",{method:"POST",headers:{"Content-Type":"application/json"},body:'{"confirm":true}'});if(r.status===409){$("status").textContent=tr().clearUnavailable;return}if(!r.ok)throw Error();epoch++;reset();poll()}catch{$("status").textContent=tr().failed}};
localize();poll();setInterval(poll,2000);document.addEventListener("visibilitychange",poll);
