"use strict";
(() => {
  const VERSION = "0.1.2";
  const themes = new Set(["auto", "light", "dark"]);
  // BEGIN GENERATED LOCALES
  const words = {"en":{"settings":"Settings","refresh":"Refresh data","available":"Available","statuses":"Service status","ok":"OK","error":"Error","warning":"Warning","unknown":"Unknown","disabled":"Disabled","app":"Application","interface":"Interface","config":"Configuration","diagnostics":"Diagnostics","version":"Installed version","latest":"Available version","timezone":"HA timezone","check":"Check version","update":"Install update","restart":"Restart","language":"Language","theme":"Theme","toast":"Notifications","import":"Import JSON","export":"Export JSON","telemetry":"Telemetry","debug":"DEBUG","name":"English","nav":"App sections","home":"Home","overview":"Overview","status":"Status","log":"LOG","ha":"Home Assistant","mqtt":"MQTT","sync":"DH Sync","overall":"Overall status","noServices":"No service data","system":"System","light":"Light","dark":"Dark"},"ru":{"settings":"Настройки","refresh":"Обновить данные","available":"Доступна","statuses":"Состояние сервисов","ok":"OK","error":"Ошибка","warning":"Внимание","unknown":"Неизвестно","disabled":"Отключено","app":"Приложение","interface":"Интерфейс","config":"Конфигурация","diagnostics":"Диагностика","version":"Установленная версия","latest":"Доступная версия","timezone":"Часовой пояс HA","check":"Проверить версию","update":"Установить обновление","restart":"Перезапустить","language":"Язык","theme":"Тема","toast":"Уведомления","import":"Импорт JSON","export":"Экспорт JSON","telemetry":"Telemetry","debug":"DEBUG","name":"Русский","nav":"Разделы приложения","home":"Главная","overview":"Обзор","status":"Статус","log":"LOG","ha":"Home Assistant","mqtt":"MQTT","sync":"DH Sync","overall":"Общее состояние","noServices":"Нет данных о сервисах","system":"Системная","light":"Светлая","dark":"Тёмная"}};
  // END GENERATED LOCALES
  const states = new Set(["ok","error","warning","unknown","disabled"]);
  const services = {ha:"HA",mqtt:"MQTT",sync:"DH Sync",telemetry:"Telemetry"};
  const serviceOrder = Object.keys(services);
  const sectionOrder = ["app","interface","config","diagnostics"];
  const validId = id => typeof id === "string" && /^[a-z][a-z0-9_-]*$/.test(id);
  const dictionary = lang => Object.hasOwn(words,lang)?words[lang]:words.en;
  function createLocale({product, haLanguage, languages, translations={}, storage, root=document.documentElement}={}) {
    if (typeof product!=="string" || !product.trim()) throw new TypeError("Locale product is required");
    const catalogs={...words,...translations};
    const supported=(languages ?? Object.keys(catalogs)).filter((id,i,a)=>a.indexOf(id)===i && Object.hasOwn(catalogs,id) && typeof catalogs[id]?.name==="string");
    if (!supported.includes("en")) throw new TypeError("English locale is required");
    const key="dh-lib-ui-language:"+product;
    let saved;
    try { storage=storage ?? globalThis.localStorage; saved=storage?.getItem(key); } catch {}
    const resolve=value=>{const id=String(value??"").toLowerCase();return supported.includes(id)?id:supported.includes(id.split("-")[0])?id.split("-")[0]:null};
    let current=resolve(saved)||resolve(haLanguage)||"en";
    const listeners=new Set();
    function apply(){root.setAttribute("lang",current)}
    apply();
    return Object.freeze({
      get language(){return current},
      get languages(){return supported.map(id=>({id,label:catalogs[id].name}))},
      t(id){return (Object.hasOwn(catalogs[current],id)?catalogs[current][id]:undefined) ?? (Object.hasOwn(words.en,id)?words.en[id]:id)},
      setLanguage(id){
        if(!supported.includes(id))throw new TypeError("Unsupported language");
        if(id===current)return;
        current=id;apply();
        try{storage?.setItem(key,id)}catch{}
        for(const callback of [...listeners]){try{callback(id)}catch(error){globalThis.console?.error("DH Lib UI locale callback",error)}}
      },
      subscribe(callback){listeners.add(callback);return ()=>listeners.delete(callback)}
    });
  }
  const translator=(locale,language)=>locale ? key=>locale.t(key) : key=>dictionary(language)[key]??key;
  const itemLabel=(item,t)=>typeof item.label==="function"?item.label():item.label ?? t(item.labelKey??item.id);
  const statusState=value=>typeof value==="string"?value:value?.state;
  const overall=values=>{
    const list=Object.values(values).map(statusState);
    return ["error","warning","unknown","ok","disabled"].find(state=>list.includes(state))??"unknown";
  };
  function relativeHref(value) {
    // Restrict to same Ingress directory, including encoded traversal and controls.
    if (typeof value !== "string" || !value || value !== value.trim() ||
        /[\\\u0000-\u0020\u007f]/.test(value) || /^[a-z][a-z0-9+.-]*:/i.test(value) ||
        value.startsWith("/") || value.startsWith("?") || value.startsWith("#")) {
      throw new TypeError("DH Lib UI requires a local relative URL");
    }
    const path = value.split(/[?#]/, 1)[0];
    let decoded;
    try { decoded = decodeURIComponent(path); } catch { throw new TypeError("Invalid URL encoding"); }
    if (decoded.includes("%") || /[\\\u0000-\u0020\u007f]/.test(decoded) ||
        decoded.startsWith("/") || /^[a-z][a-z0-9+.-]*:/i.test(decoded) ||
        decoded.split("/").includes("..")) throw new TypeError("Unsafe relative URL");
    return value;
  }
  function setTheme(theme, root = document.documentElement) {
    if (!themes.has(theme)) throw new TypeError("Invalid DH Lib UI theme");
    root.setAttribute("data-dh-lib-ui-theme", theme);
  }
  function mount({target, title, version, availableVersion, iconHref, items, active, language = "en", locale, onNavigate, statuses = {}, statusTarget, onRefresh}) {
    if (!target || typeof target.replaceChildren !== "function" || !Array.isArray(items) ||
        typeof title !== "string" || !title.trim()) throw new TypeError("Invalid shell options");
    const doc = target.ownerDocument;
    const t = translator(locale,language);
    if (onRefresh !== undefined && typeof onRefresh !== "function") throw new TypeError("Invalid refresh callback");
    function validateStatuses(values) {
      if (!values || typeof values !== "object" || Array.isArray(values)) throw new TypeError("Invalid statuses");
      for (const [id,state] of Object.entries(values)) {
        if (!serviceOrder.includes(id) || !states.has(statusState(state))) throw new TypeError("Invalid service status: "+id);
        if(typeof state==="object" && state.details!==undefined && (!Array.isArray(state.details)||state.details.some(d=>!d||typeof d.label!=="string"||typeof d.value!=="string")))throw new TypeError("Invalid service details");
      }
    }
    validateStatuses(statuses);
    const create = (tag, cls, value) => {
      const node = doc.createElement(tag);
      if (cls) node.className = cls;
      if (value !== undefined) node.textContent = String(value);
      return node;
    };
    if(statusTarget && typeof onNavigate!=="function")throw new TypeError("Status page needs onNavigate");
    if(statusTarget && (statusTarget===target || statusTarget.ownerDocument!==doc || typeof statusTarget.replaceChildren!=="function"))throw new TypeError("Invalid status target");
    items=[...items];
    if(!items.some(item=>item?.id==="status"))items.push({id:"status",labelKey:"status"});
    const ids = new Set();
    for (const item of items) {
      if (!item || typeof item.id !== "string" || !item.id || ids.has(item.id) ||
          typeof itemLabel(item,t) !== "string" || !itemLabel(item,t).trim()) throw new TypeError("Invalid menu item");
      ids.add(item.id);
      if (item.href !== undefined) relativeHref(item.href);
      else if (item.id!=="status" && typeof onNavigate !== "function") throw new TypeError("Internal navigation needs onNavigate");
    }
    if (active != null && !ids.has(active)) throw new TypeError("Unknown active menu item");
    if (iconHref !== undefined) relativeHref(iconHref);
    const header = create("header", "dh-lib-ui-header");
    const heading = create("div", "dh-lib-ui-heading");
    if (iconHref !== undefined) {
      const icon = create("img", "dh-lib-ui-icon");
      icon.src = iconHref;
      icon.alt = "";
      heading.append(icon);
    }
    const identity=create("div","dh-lib-ui-identity");
    identity.append(create("h1","dh-lib-ui-title",title));
    heading.append(identity);
    const versionNode = create("span","dh-lib-ui-version",version == null ? "" : "v" + version);
    identity.append(versionNode);
    const updateNode = create("span","dh-lib-ui-available");
    identity.append(updateNode);
    let installed, availableValue;
    function setVersion(value, available) {
      installed=value;availableValue=available;
      versionNode.textContent = value == null ? "" : "v" + value;
      updateNode.textContent = available != null && available !== value ? t("available") + " v" + available : "";
      updateNode.hidden = !updateNode.textContent;
    }
    setVersion(version, availableVersion);
    let languageSelect,languageCode;
    if(locale){
      const picker=create("span","dh-lib-ui-language-picker");
      languageCode=create("span","dh-lib-ui-language-code");
      languageCode.setAttribute("aria-hidden","true");
      languageSelect=create("select","dh-lib-ui-language");
      for(const entry of locale.languages){
        const option=create("option","",entry.label);option.value=entry.id;languageSelect.append(option);
      }
      languageSelect.value=locale.language;
      languageSelect.addEventListener("change",()=>locale.setLanguage(languageSelect.value));
      picker.append(languageCode,languageSelect);heading.append(picker);
    }
    const nav = create("nav","dh-lib-ui-nav");
    nav.setAttribute("aria-label", t("nav"));
    const entries = new Map();
    const ordered = [...items.filter(item=>!["log","status"].includes(item.id)),...items.filter(item=>item.id==="status"),...items.filter(item=>item.id==="log")];
    for (const item of ordered) {
      const link = item.href !== undefined;
      const node = create(link ? "a" : "button","dh-lib-ui-nav-item");
      node.append(create("span","dh-lib-ui-nav-label",itemLabel(item,t)));
      if (item.id === "log") node.className += " dh-lib-ui-nav-log";
      if (link) node.setAttribute("href",item.href);
      else {
        node.type = "button";
        node.addEventListener("click", () => {
          if(item.id==="status" && !statusTarget){panel.hidden=!panel.hidden;node.setAttribute("aria-expanded",String(!panel.hidden));return}
          onNavigate?.(item.id);
        });
      }
      nav.append(node);
      entries.set(item.id,node);
    }
    header.append(heading,nav);
    const statusEntry=entries.get("status");
    const dot=create("span","dh-lib-ui-status-dot");
    statusEntry.append(dot);
    const panel=create("section","dh-lib-ui-status-panel");
    const statusList=create("div","dh-lib-ui-settings");
    const empty=create("p","dh-lib-ui-status-empty");
    panel.append(statusList,empty);
    if(!statusTarget){panel.hidden=true;statusEntry.setAttribute("aria-expanded","false");header.append(panel)}
    const statusNodes=new Map();
    for(const id of serviceOrder){
      const node=create("section","dh-lib-ui-panel dh-lib-ui-status-card");
      const line=create("div","dh-lib-ui-status-heading");
      const name=create("h2","dh-lib-ui-settings-title");
      const state=create("span","dh-lib-ui-service-state");
      line.append(name,state);
      const details=create("div","dh-lib-ui-status-details");
      node.append(line,details);statusList.append(node);statusNodes.set(id,{node,name,state,details});
    }
    const refresh=onRefresh && create("button","dh-lib-ui-nav-item dh-lib-ui-refresh","⟳");
    if(refresh){refresh.type="button";refresh.addEventListener("click",onRefresh);nav.append(refresh)}
    let snapshot={};
    function setStatuses(values){
      validateStatuses(values);snapshot={...values};
      for(const id of serviceOrder){
        const {node,name,state,details}=statusNodes.get(id),value=values[id],kind=statusState(value);
        node.hidden=value===undefined;name.textContent=t(id);
        if(value===undefined)continue;
        node.setAttribute("data-dh-lib-ui-state",kind);state.textContent=t(kind);
        details.replaceChildren(...(value.details??[]).map(detail=>{
          const row=create("div","dh-lib-ui-settings-row");
          row.append(create("span","dh-lib-ui-settings-label",detail.label),create("span","dh-lib-ui-settings-value",detail.value));return row;
        }));
      }
      const kind=overall(values);
      dot.setAttribute("data-dh-lib-ui-state",kind);
      statusEntry.setAttribute("aria-label",t("status")+" · "+t(kind));statusEntry.title=t("overall")+": "+t(kind);
      statusEntry.hidden=!statusTarget && Object.keys(values).length===0;
      empty.hidden=Object.keys(values).length!==0;empty.textContent=t("noServices");
      if(statusEntry.hidden&&!statusTarget){panel.hidden=true;statusEntry.setAttribute("aria-expanded","false")}
    }
    function localize(){
      nav.setAttribute("aria-label",t("nav"));
      for(const item of items){
        const node=entries.get(item.id);
        node.children[0].textContent=itemLabel(item,t);
        if(locale && item.id==="log" && item.href!==undefined){
          const [before,hash]=item.href.split("#",2), separator=before.indexOf("?");
          const path=separator<0?before:before.slice(0,separator);
          const params=new URLSearchParams(separator<0?"":before.slice(separator+1));
          params.set("lang",locale.language);
          node.setAttribute("href",path+"?"+params.toString()+(hash===undefined?"":"#"+hash));
        }
      }
      if(languageSelect){
        languageSelect.value=locale.language;
        const entry=locale.languages.find(item=>item.id===locale.language);
        const code=locale.language.split("-")[0].toUpperCase();
        languageCode.textContent=code;
        languageSelect.setAttribute("aria-label",t("language"));
        languageSelect.title=entry?.label ?? t("language");
      }
      if(refresh){refresh.setAttribute("aria-label",t("refresh"));refresh.title=t("refresh")}
      setVersion(installed,availableValue);setStatuses(snapshot);
    }
    setStatuses(statuses);localize();
    if(statusTarget)statusTarget.replaceChildren(panel);
    const unsubscribe=locale?.subscribe(localize);
    const setActive = id => {
      if (id != null && !entries.has(id)) throw new TypeError("Unknown active menu item");
      if(!statusTarget){panel.hidden=true;statusEntry.setAttribute("aria-expanded","false")}
      for (const [key,node] of entries) {
        if (key === id) node.setAttribute("aria-current","page");
        else node.removeAttribute("aria-current");
      }
    };
    setActive(active);
    target.replaceChildren(header);
    return Object.freeze({
      setActive,
      setVersion, setStatuses,
      setRefreshDisabled(value) { if (refresh) refresh.disabled = Boolean(value); },
      destroy() { unsubscribe?.();panel.remove();header.remove(); }
    });
  }
  // Build common settings sections once. The App owns all supplied controls,
  // callbacks, pending state, validation, and persisted preferences.
  function mountSettings({target, language="en", locale, sections}) {
    if (!target || typeof target.replaceChildren !== "function" || !Array.isArray(sections)) throw new TypeError("Invalid settings options");
    const doc = target.ownerDocument, t = translator(locale,language);
    const create = (tag,cls,text) => {
      const node=doc.createElement(tag); node.className=cls;
      if (text !== undefined) node.textContent=String(text);
      return node;
    };
    const ids=new Set(), groups=new Set(), values=new Map(), actions=new Map();
    const label = item => itemLabel(item,t);
    const localized=[];
    for (const section of sections) {
      if (!section || !sectionOrder.includes(section.id) || groups.has(section.id) ||
          !Array.isArray(section.rows ?? []) || !Array.isArray(section.actions ?? [])) throw new TypeError("Invalid settings section");
      groups.add(section.id);
      for (const item of [...(section.rows ?? []),...(section.actions ?? [])]) {
        if (!item || !validId(item.id) || ids.has(item.id) || typeof label(item)!=="string" || !label(item).trim()) throw new TypeError("Invalid settings item");
        ids.add(item.id);
      }
      for (const row of section.rows ?? []) {
        if (row.control !== undefined && (!row.control || row.control.ownerDocument!==doc || row.value !== undefined)) throw new TypeError("Invalid settings control");
      }
      for (const action of section.actions ?? []) if (typeof action.onClick !== "function") throw new TypeError("Invalid settings action");
    }
    const layout=create("div","dh-lib-ui-settings");
    for (const id of sectionOrder) {
      const section=sections.find(s=>s.id===id);
      if (!section) continue;
      const panel=create("section","dh-lib-ui-panel dh-lib-ui-settings-panel");
      const heading=create("h2","dh-lib-ui-settings-title",t(id));panel.append(heading);localized.push([heading,()=>t(id)]);
      for (const row of section.rows ?? []) {
        const line=create("div","dh-lib-ui-settings-row");
        const rowLabel=create("span","dh-lib-ui-settings-label",label(row));line.append(rowLabel);localized.push([rowLabel,()=>label(row)]);
        if (row.control !== undefined) {
          const slot=create("div","dh-lib-ui-settings-control");
          slot.append(row.control); line.append(slot);
        } else {
          const value=create("span","dh-lib-ui-settings-value",row.value ?? "—");
          values.set(row.id,value); line.append(value);
        }
        panel.append(line);
      }
      if ((section.actions ?? []).length) {
        const list=create("div","dh-lib-ui-actions");
        for (const action of section.actions) {
          const button=create("button","dh-lib-ui-button"+(action.primary?" dh-lib-ui-primary":""),label(action));
          button.type="button"; button.disabled=Boolean(action.disabled);localized.push([button,()=>label(action)]);
          button.addEventListener("click",action.onClick); actions.set(action.id,button); list.append(button);
        }
        panel.append(list);
      }
      layout.append(panel);
    }
    target.replaceChildren(layout);
    const unsubscribe=locale?.subscribe(()=>{for(const [node,text] of localized)node.textContent=text()});
    return Object.freeze({
      setValue(id,value) {
        if (!values.has(id)) throw new TypeError("Unknown settings value");
        values.get(id).textContent=value ?? "—";
      },
      setDisabled(id,value) {
        if (!actions.has(id)) throw new TypeError("Unknown settings action");
        actions.get(id).disabled=Boolean(value);
      },
      destroy() { unsubscribe?.();layout.remove(); }
    });
  }
  globalThis.DHLibUI = Object.freeze({VERSION, mount, mountSettings, setTheme, createLocale});
})();
