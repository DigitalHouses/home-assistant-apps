"use strict";
(() => {
  const VERSION = "0.1.0";
  const themes = new Set(["auto", "light", "dark"]);
  const labels = {en:"App sections",ru:"Разделы приложения"};
  const words = {
    en:{settings:"Settings",refresh:"Refresh data",available:"Available",statuses:"Service status",ok:"OK",error:"Error",warning:"Warning",unknown:"Unknown",disabled:"Disabled",app:"Application",interface:"Interface",config:"Configuration",diagnostics:"Diagnostics",version:"Installed version",latest:"Available version",timezone:"HA timezone",check:"Check version",update:"Install update",restart:"Restart",language:"Language",theme:"Theme",toast:"Notifications",import:"Import JSON",export:"Export JSON",telemetry:"Telemetry",debug:"DEBUG"},
    ru:{settings:"Настройки",refresh:"Обновить данные",available:"Доступна",statuses:"Состояние сервисов",ok:"OK",error:"Ошибка",warning:"Внимание",unknown:"Неизвестно",disabled:"Отключено",app:"Приложение",interface:"Интерфейс",config:"Конфигурация",diagnostics:"Диагностика",version:"Установленная версия",latest:"Доступная версия",timezone:"Часовой пояс HA",check:"Проверить версию",update:"Установить обновление",restart:"Перезапустить",language:"Язык",theme:"Тема",toast:"Уведомления",import:"Импорт JSON",export:"Экспорт JSON",telemetry:"Telemetry",debug:"DEBUG"}
  };
  const states = new Set(["ok","error","warning","unknown","disabled"]);
  const services = {ha:"HA",mqtt:"MQTT",sync:"DH Sync",telemetry:"Telemetry"};
  const serviceOrder = Object.keys(services);
  const sectionOrder = ["app","interface","config","diagnostics"];
  const validId = id => typeof id === "string" && /^[a-z][a-z0-9_-]*$/.test(id);
  const dictionary = lang => words[lang] || words.en;
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
  function mount({target, title, version, availableVersion, iconHref, items, active, language = "en", onNavigate, statuses = {}, onRefresh}) {
    if (!target || typeof target.replaceChildren !== "function" || !Array.isArray(items) ||
        typeof title !== "string" || !title.trim()) throw new TypeError("Invalid shell options");
    const doc = target.ownerDocument;
    const t = dictionary(language);
    if (onRefresh !== undefined && typeof onRefresh !== "function") throw new TypeError("Invalid refresh callback");
    function validateStatuses(values) {
      if (!values || typeof values !== "object" || Array.isArray(values)) throw new TypeError("Invalid statuses");
      for (const [id,state] of Object.entries(values)) {
        if (!serviceOrder.includes(id) || !states.has(state)) throw new TypeError("Invalid service status: "+id);
      }
    }
    validateStatuses(statuses);
    const create = (tag, cls, value) => {
      const node = doc.createElement(tag);
      if (cls) node.className = cls;
      if (value !== undefined) node.textContent = String(value);
      return node;
    };
    const ids = new Set();
    for (const item of items) {
      if (!item || typeof item.id !== "string" || !item.id || ids.has(item.id) ||
          typeof item.label !== "string" || !item.label.trim()) throw new TypeError("Invalid menu item");
      ids.add(item.id);
      if (item.href !== undefined) relativeHref(item.href);
      else if (typeof onNavigate !== "function") throw new TypeError("Internal navigation needs onNavigate");
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
    heading.append(create("h1","dh-lib-ui-title",title));
    const versionNode = create("span","dh-lib-ui-version",version == null ? "" : "v" + version);
    heading.append(versionNode);
    const updateNode = create("span","dh-lib-ui-available");
    heading.append(updateNode);
    function setVersion(value, available) {
      versionNode.textContent = value == null ? "" : "v" + value;
      updateNode.textContent = available != null && available !== value ? t.available + " v" + available : "";
      updateNode.hidden = !updateNode.textContent;
    }
    setVersion(version, availableVersion);
    const nav = create("nav","dh-lib-ui-nav");
    nav.setAttribute("aria-label", labels[language] || labels.en);
    const entries = new Map();
    const ordered = [...items.filter(item=>item.id!=="log"),...items.filter(item=>item.id==="log")];
    for (const item of ordered) {
      const link = item.href !== undefined;
      const node = create(link ? "a" : "button","dh-lib-ui-nav-item",item.label);
      if (item.id === "log") node.className += " dh-lib-ui-nav-log";
      if (link) node.setAttribute("href",item.href);
      else {
        node.type = "button";
        node.addEventListener("click", () => onNavigate(item.id));
      }
      nav.append(node);
      entries.set(item.id,node);
    }
    header.append(heading,nav);
    const bar = create("div","dh-lib-ui-statusbar");
    bar.setAttribute("role","group");
    bar.setAttribute("aria-label",t.statuses);
    const statusNodes = new Map();
    const statusList = create("div","dh-lib-ui-status-list");
    bar.append(statusList);
    for (const id of serviceOrder) {
      const node = create("span","dh-lib-ui-service");
      const name = create("span","dh-lib-ui-service-name",services[id]);
      const state = create("span","dh-lib-ui-service-state");
      node.append(name,state);
      statusList.append(node);
      statusNodes.set(id,{node,state});
    }
    const refresh = onRefresh && create("button","dh-lib-ui-button dh-lib-ui-refresh",t.refresh);
    if (refresh) {
      refresh.type = "button";
      refresh.addEventListener("click",onRefresh);
      bar.append(refresh);
    }
    function setStatuses(values) {
      validateStatuses(values);
      for (const id of serviceOrder) {
        const {node,state} = statusNodes.get(id);
        const value = values[id];
        node.hidden = value === undefined;
        if (value !== undefined) {
          node.setAttribute("data-dh-lib-ui-state",value);
          state.textContent = t[value];
        }
      }
      bar.hidden = Object.keys(values).length === 0 && !refresh;
    }
    setStatuses(statuses);
    header.append(bar);
    const setActive = id => {
      if (id != null && !entries.has(id)) throw new TypeError("Unknown active menu item");
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
      destroy() { header.remove(); }
    });
  }
  // Build common settings sections once. The App owns all supplied controls,
  // callbacks, pending state, validation, and persisted preferences.
  function mountSettings({target, language="en", sections}) {
    if (!target || typeof target.replaceChildren !== "function" || !Array.isArray(sections)) throw new TypeError("Invalid settings options");
    const doc = target.ownerDocument, t = dictionary(language);
    const create = (tag,cls,text) => {
      const node=doc.createElement(tag); node.className=cls;
      if (text !== undefined) node.textContent=String(text);
      return node;
    };
    const ids=new Set(), groups=new Set(), values=new Map(), actions=new Map();
    const label = item => item.label ?? t[item.id];
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
      panel.append(create("h2","dh-lib-ui-settings-title",t[id]));
      for (const row of section.rows ?? []) {
        const line=create("div","dh-lib-ui-settings-row");
        line.append(create("span","dh-lib-ui-settings-label",label(row)));
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
          button.type="button"; button.disabled=Boolean(action.disabled);
          button.addEventListener("click",action.onClick); actions.set(action.id,button); list.append(button);
        }
        panel.append(list);
      }
      layout.append(panel);
    }
    target.replaceChildren(layout);
    return Object.freeze({
      setValue(id,value) {
        if (!values.has(id)) throw new TypeError("Unknown settings value");
        values.get(id).textContent=value ?? "—";
      },
      setDisabled(id,value) {
        if (!actions.has(id)) throw new TypeError("Unknown settings action");
        actions.get(id).disabled=Boolean(value);
      },
      destroy() { layout.remove(); }
    });
  }
  globalThis.DHLibUI = Object.freeze({VERSION, mount, mountSettings, setTheme});
})();
