"use strict";
/* Reusable read-only picker. Selection modifies the caller's draft only.
   Filter and selection rules follow the DH Climate entity picker. */
(() => {
  let dialog = null;
  const NONE = "__none__", ALL = "__all__", LIMIT = 16, PAGE = 150;
  const el = (tag, label, cls) => {
    const node = document.createElement(tag);
    if (label !== undefined) node.textContent = String(label);
    if (cls) node.className = cls;
    return node;
  };
  const domainOf = t => t.domain || t.entity_id.split(".")[0];
  const areaOf = t => t.area_id || (t.area && t.area !== "Без комнаты" ? t.area : null);
  const available = t => !!t && !t.missing && typeof t.state === "string" &&
    !["unavailable","unknown",""].includes(t.state);
  function matches(t, f) {
    if (!f.domains.includes(domainOf(t))) return false;
    if (f.domain !== ALL && domainOf(t) !== f.domain) return false;
    if (f.area !== ALL && (areaOf(t) || NONE) !== f.area) return false;
    if (f.integration !== ALL && (t.integration || NONE) !== f.integration) return false;
    if (f.availability !== ALL && available(t) !== (f.availability === "available")) return false;
    return [t.name,t.entity_id,t.area,t.device_name,t.integration].filter(Boolean)
      .join(" ").toLocaleLowerCase().includes(f.query.trim().toLocaleLowerCase());
  }
  function resolveArea(items, areaId, hint) {
    if (areaId) return items.some(t => areaOf(t) === areaId) ? areaId : ALL;
    const match = items.find(t => areaOf(t) && t.area && t.area.toLocaleLowerCase() ===
      (hint || "").toLocaleLowerCase());
    return match ? areaOf(match) : ALL;
  }
  function displayed(items, chosen, filters) {
    const found = items.filter(t => matches(t, filters));
    const ids = new Set(found.map(t => t.entity_id));
    const byId = new Map(items.map(t => [t.entity_id,t]));
    const selected = [...chosen].map(id => byId.get(id) ||
      {entity_id:id,name:id,missing:true});
    const remaining = found.filter(t => !chosen.has(t.entity_id))
      .sort((a,b) => (a.name || a.entity_id).localeCompare(b.name || b.entity_id,"ru"));
    return {count:found.length,rows:[...selected,...remaining.slice(0,PAGE)],
      outside: new Set(selected.filter(t=>!ids.has(t.entity_id)).map(t=>t.entity_id)),
      truncated:remaining.length>PAGE};
  }
  function initialData(operation,t) {
    if(operation==="position")return {position:Number.isInteger(t?.position)?t.position:50};
    if(operation==="hvac_mode")return {hvac_mode:t?.hvac_modes?.includes(t.state)?t.state:""};
    if(operation==="temperature")return {temperature:Number.isFinite(t?.temperature)?t.temperature:null,temperature_unit:t?.temperature_unit};
    if(operation==="volume")return {volume_pct:t?.volume_pct??null};
    return {};
  }
  function mergeAssignments(old, ids, items=[]) {
    const byId=new Map(old.map(a=>[a.entity_id,a]));
    return ids.map(id=>{
      if(byId.has(id))return byId.get(id);
      const t=items.find(t=>t.entity_id===id);
      const operation=/^(cover|climate|media_player)\./.test(id)?(t?.operations?.[0]||"toggle"):"toggle";
      return {entity_id:id,operation,data:initialData(operation,t)};
    });
  }
  function close() {
    if (!dialog) return;
    const old=dialog;dialog=null;old.close();old.remove();
  }
  function select(label, choices, initial) {
    const node=el("select");
    node.setAttribute("aria-label",label);
    for(const [value,name] of choices){
      const opt=el("option",name);opt.value=value;node.append(opt);
    }
    node.value=initial;return node;
  }
  function open({items,values=[],domains=["light","switch","cover","climate","media_player"],areaId,areaHint,usage={},onConfirm,renderIcon,renderTest}) {
    close();
    const chosen=new Set(values), original=new Set(values);
    const eligible=items.filter(t=>domains.includes(domainOf(t))&&(!["cover","climate","media_player"].includes(domainOf(t))||t.operations?.length));
    const filters={domains,domain:ALL,area:resolveArea(eligible,areaId,areaHint),
      integration:ALL,availability:ALL,query:""};
    const d=el("dialog",undefined,"entity-picker");dialog=d;
    d.setAttribute("aria-label","Выбор сущностей");
    d.addEventListener("cancel",e=>{e.preventDefault();close()});
    d.addEventListener("click",e=>{if(e.target===d){
      const r=d.getBoundingClientRect();
      if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close();
    }});
    const head=el("div",undefined,"head"), exit=el("button","×");
    exit.type="button";exit.setAttribute("aria-label","Закрыть");exit.onclick=close;
    head.append(el("h2","Выбор сущностей"),exit);d.append(head);
    const filtersRow=el("div",undefined,"picker-filters");
    const search=el("input");search.type="search";search.placeholder="Имя, entity_id, устройство…";
    search.setAttribute("aria-label","Поиск сущностей");
    const areas=new Map(eligible.filter(t=>areaOf(t)).map(t=>[areaOf(t),t.area||areaOf(t)]));
    const integrations=[...new Set(eligible.map(t=>t.integration).filter(Boolean))].sort();
    const area=select("Комната",[[ALL,"Все комнаты"],[NONE,"Без комнаты"],...Array.from(areas).sort((a,b)=>a[1].localeCompare(b[1],"ru"))],filters.area);
    const domain=select("Домен",[[ALL,"Все домены"],...domains.map(x=>[x,x])],ALL);
    const source=select("Интеграция",[[ALL,"Все интеграции"],...integrations.map(x=>[x,x]),[NONE,"Без интеграции"]],ALL);
    const status=select("Доступность",[[ALL,"Все состояния"],["available","Доступные"],["unavailable","Недоступные"]],ALL);
    filtersRow.append(search,area,domain,source,status);d.append(filtersRow);
    const count=el("div",undefined,"muted picker-count"),list=el("div",undefined,"picker-results");
    list.setAttribute("role","listbox");list.setAttribute("aria-multiselectable","true");
    d.append(count,list);
    const footer=el("div",undefined,"picker-footer"),summary=el("span",undefined,"muted");
    const cancel=el("button","Отмена"),confirm=el("button","Применить выбор","save");
    cancel.type=confirm.type="button";cancel.onclick=close;
    confirm.onclick=()=>{const result=[...chosen];close();onConfirm(result)};
    footer.append(summary,cancel,confirm);d.append(footer);
    function refresh(){
      const view=displayed(eligible,chosen,filters);list.replaceChildren();
      count.textContent="Найдено: "+view.count+(view.truncated?" · Уточните фильтры":"");
      for(const t of view.rows){
        const id=t.entity_id,checked=chosen.has(id);
        const row=el("button",undefined,"picker-result"+(checked?" is-selected":""));
        row.type="button";row.setAttribute("role","option");row.setAttribute("aria-selected",String(checked));
        row.disabled=!checked&&(chosen.size>=LIMIT||(!original.has(id)&&!domains.includes(domainOf(t))));
        row.append(el("span",checked?"☑":"□","picker-tick"));
        if(renderIcon)row.append(renderIcon(t,id));
        const info=el("span",undefined,"picker-info");
        info.append(el("strong",t.name||id),el("span",id,"muted picker-id"),
          el("span",[t.area,t.device_name,t.integration].filter(Boolean).join(" · "),"muted"));
        if(usage[id]?.length)info.append(el("span","Назначено: "+usage[id].join(", "),"muted"));
        if(view.outside.has(id)&&!t.missing)info.append(el("span","Вне фильтра","muted"));
        row.append(info);
        const test=renderTest?renderTest(t,id):null;
        if(!test)row.append(el("span",t.missing?"Не найдено":available(t)?t.state:"Недоступно",
          "picker-state"+(available(t)?"":" problem")));
        row.onclick=()=>{if(chosen.has(id))chosen.delete(id);else if(chosen.size<LIMIT)chosen.add(id);refresh()};
        // Separate sibling button: testing must never change selection.
        const line=el("div",undefined,"picker-line");
        line.append(row);
        if(test)line.append(test);
        list.append(line);
      }
      if(!view.rows.length)list.append(el("p","Нет подходящих сущностей","muted"));
      summary.textContent="Выбрано: "+chosen.size+" / "+LIMIT;
      confirm.disabled=chosen.size>LIMIT;
    }
    search.oninput=()=>{filters.query=search.value;refresh()};
    for(const [node,key] of [[area,"area"],[domain,"domain"],[source,"integration"],[status,"availability"]])
      node.onchange=()=>{filters[key]=node.value;refresh()};
    document.body.append(d);d.showModal();refresh();search.focus();
  }
  globalThis.DHActionsEntityPicker={open,close,matches,resolveArea,displayed,mergeAssignments,initialData,ALL,NONE};
})();
