"use strict";
(function(global){
  const labels={
    ru:{enabled:"Показывать уведомления",duration:"Время показа, мин",close:"Закрыть уведомление",region:"Уведомления"},
    en:{enabled:"Show notifications",duration:"Display time, min",close:"Dismiss notification",region:"Notifications"}
  };
  const validMinutes=n=>Number.isInteger(n)&&n>=1&&n<=1440;
  const defaults={enabled:true,minutes:60};
  function mount(options={}){
    const doc=global.document;
    const product=options.product;
    if(typeof product!=="string"||!product)throw new Error("DH Journal Toast: product is required");
    const endpoint=options.endpoint||"./api/log/toasts";
    const onEvents=typeof options.onEvents==="function"?options.onEvents:null;
    const language=()=>((typeof options.language==="function"?options.language():options.language)||doc.documentElement.lang)==="ru"?"ru":"en";
    const t=()=>labels[language()];
    const key="dh-journal-toasts:"+product;
    let settings={...defaults};
    try{
      const stored=JSON.parse(global.localStorage.getItem(key)||"null");
      if(stored){if(typeof stored.enabled==="boolean")settings.enabled=stored.enabled;if(validMinutes(stored.minutes))settings.minutes=stored.minutes}
    }catch{}
    let cursor=null, busy=false, disposed=false, epoch=0, displayBaseline=false;
    const active=new Map();
    const stack=doc.createElement("section");
    stack.className="dh-toast-stack";
    stack.setAttribute("aria-label",t().region);
    stack.setAttribute("aria-live","polite");
    stack.setAttribute("aria-relevant","additions");
    doc.body.append(stack);
    function dismiss(id){
      const item=active.get(id);if(!item)return;
      global.clearTimeout(item.timer);item.node.remove();active.delete(id);
    }
    function schedule(id){
      const item=active.get(id);if(!item)return;
      global.clearTimeout(item.timer);
      const remaining=item.shown+settings.minutes*60000-Date.now();
      if(remaining<=0)dismiss(id);
      else item.timer=global.setTimeout(()=>dismiss(id),remaining);
    }
    function show(row){
      if(active.has(row.id))return;
      const node=doc.createElement("article");
      node.className="dh-toast "+(["debug","info","success","pending","warning","error","lifecycle"].includes(row.level)?row.level:"info");
      const icon=doc.createElement("span");icon.textContent=row.icon||"ℹ️";icon.setAttribute("aria-hidden","true");
      const body=doc.createElement("div");
      const msg=doc.createElement("div");msg.className="dh-toast-message";msg.textContent=row.message;
      const time=doc.createElement("time");time.className="dh-toast-time";time.dateTime=row.ts;time.textContent=row.local_time;
      body.append(msg,time);
      const close=doc.createElement("button");close.type="button";close.className="dh-toast-close";close.textContent="×";close.setAttribute("aria-label",t().close);close.onclick=()=>dismiss(row.id);
      node.append(icon,body,close);
      // DOM and visual order: latest on top, oldest anchored at bottom.
      stack.prepend(node);
      active.set(row.id,{node,shown:Date.now(),timer:null});
      schedule(row.id);
    }
    async function poll(){
      if(disposed||busy||(!settings.enabled&&!onEvents)||doc.hidden)return;
      busy=true;const current=epoch;
      try{
        const params=new URLSearchParams({lang:language()});
        if(cursor!==null)params.set("after",String(cursor));
        const url=new URL(endpoint,doc.baseURI);url.search=params.toString();
        const r=await global.fetch(url,{cache:"no-store",credentials:"same-origin"});
        if(!r.ok)throw new Error("HTTP");
        const data=await r.json();
        if(disposed||current!==epoch||(!settings.enabled&&!onEvents))return;
        if(!Number.isSafeInteger(data.cursor)||data.cursor<0||!Array.isArray(data.rows))return;
        const previous=cursor;
        if(previous!==null&&data.cursor<previous){for(const id of active.keys())dismiss(id)}
        cursor=data.cursor;
        if(previous!==null&&data.cursor>=previous){
          const fresh=data.rows.filter(row=>Number.isSafeInteger(row.id)&&row.id>previous&&row.id<=cursor);
          if(settings.enabled&&!displayBaseline)for(const row of fresh)show(row);
          // A consumer may react to the event batch even when presentation is disabled.
          // Callback errors must not interrupt polling or change notification timers.
          if(onEvents&&fresh.length)try{Promise.resolve(onEvents(fresh)).catch(()=>{})}catch{}
        }
        displayBaseline=false;
      }catch{}finally{busy=false;if(!disposed&&current!==epoch)poll()}
    }
    let controls=null,enabledInput=null,minutesInput=null;
    function syncControls(){if(enabledInput){enabledInput.checked=settings.enabled;minutesInput.value=String(settings.minutes);minutesInput.disabled=!settings.enabled}}
    function configure(next={}){
      if(disposed)return {...settings};
      const wasEnabled=settings.enabled;
      if(typeof next.enabled==="boolean")settings.enabled=next.enabled;
      if(validMinutes(next.minutes))settings.minutes=next.minutes;
      try{global.localStorage.setItem(key,JSON.stringify(settings))}catch{}
      syncControls();
      if(wasEnabled!==settings.enabled){
        epoch++;for(const id of active.keys())dismiss(id);
        if(onEvents){
          // Keep the event cursor for the consumer. Re-enabling presentation
          // establishes a fresh display baseline without replaying missed toasts.
          displayBaseline=settings.enabled;
          poll();
        }else{
          cursor=null;
          if(settings.enabled)poll();
        }
      }else{for(const id of active.keys())schedule(id)}
      return {...settings};
    }
    if(options.settingsTarget){
      controls=doc.createElement("div");controls.className="dh-toast-settings";
      const enabledLabel=doc.createElement("label");enabledInput=doc.createElement("input");enabledInput.type="checkbox";
      const enabledText=doc.createElement("span");enabledText.textContent=t().enabled;enabledLabel.append(enabledInput,enabledText);
      const minutesLabel=doc.createElement("label");const minutesText=doc.createElement("span");minutesText.textContent=t().duration;
      minutesInput=doc.createElement("input");minutesInput.type="number";minutesInput.min="1";minutesInput.max="1440";minutesInput.step="1";minutesLabel.append(minutesText,minutesInput);
      enabledInput.onchange=()=>configure({enabled:enabledInput.checked});
      minutesInput.onchange=()=>configure({minutes:Number(minutesInput.value)});
      controls.append(enabledLabel,minutesLabel);options.settingsTarget.append(controls);syncControls();
    }
    function onVisibility(){if(!doc.hidden){for(const id of active.keys())schedule(id);poll()}}
    const interval=global.setInterval(poll,5000);
    doc.addEventListener("visibilitychange",onVisibility);poll();
    return {configure,settings:()=>({...settings}),poll,destroy(){
      if(disposed)return;disposed=true;epoch++;global.clearInterval(interval);doc.removeEventListener("visibilitychange",onVisibility);
      for(const id of active.keys())dismiss(id);stack.remove();if(controls)controls.remove();
    }};
  }
  global.DHJournalToast={mount};
})(globalThis);
