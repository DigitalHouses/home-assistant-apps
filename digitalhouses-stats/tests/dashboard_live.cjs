const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

class Element {
  constructor(){this.children=[];this.style={};this.attrs={};this.events={};this.textContent="";this.parent=null;}
  append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node)}}
  prepend(node){node.parent=this;this.children.unshift(node)}
  appendChild(node){this.append(node);return node}
  replaceChildren(){this.children=[]}
  insertCell(){const e=new Element();this.append(e);return e}
  setAttribute(k,v){this.attrs[k]=v}
  addEventListener(k,cb){this.events[k]=cb}
  insertAdjacentHTML(){}
  set innerHTML(v){this.children=[];if(this.onRender)this.onRender()}
  remove(){if(this.parent){this.parent.children=this.parent.children.filter(x=>x!==this);this.parent=null}}
}

test("notification batch refreshes data, not toast nodes or timers; disabled mode and manual refresh",async()=>{
  const elements=new Map(), body=new Element(), responses=[], calls=[], intervals=[], timers=new Map(), storage=new Map();
  const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
  const document={body,hidden:false,documentElement:{lang:"en"},baseURI:"http://test.local/",getElementById:get,createElement:()=>new Element(),addEventListener(){},removeEventListener(){}};
  const window={scrollX:0,scrollY:240,scrollTo({left,top}){this.scrollX=left;this.scrollY=top}};
  let count=50, seq=0, hold=null, zone="Europe/Berlin";
  const context={document,window,Intl,console,URL,URLSearchParams,Date,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},setInterval:fn=>{intervals.push(fn);return ++seq},clearInterval(){},setTimeout:(fn,ms)=>{timers.set(++seq,{fn,ms});return seq},clearTimeout:id=>timers.delete(id),fetch:async url=>{
    const p=new URL(String(url),"http://test.local/").pathname;calls.push(p);
    let data;
    if(p==="/api/log/toasts")data=responses.shift();
    else {
      if(hold)await hold;
      if(p==="/api/summary")data={observed_installations:count,active_24h:count,active_7d:count,active_30d:count,heartbeats:count+300,timezone:zone,timezone_fallback:false,last_heartbeat:"2026-07-01T12:00:00Z"};
      else if(p==="/api/countries")data=[{country:"KZ",observed_installations:count,products:[{name:"PVE",observed_installations:count}]}];
      else if(p==="/api/versions")data=[{product:"pve",name:"PVE",version:"1.0.0",observed_installations:count,active_7d:count}];
      else data=[{day:"2026-11-28",total_installations:count,active_installations:count}];
    }
    return {ok:true,json:async()=>data};
  }};
  vm.createContext(context);
  const dashboard=path.join(__dirname,"../dashboard");
  const run=file=>vm.runInContext(fs.readFileSync(path.join(dashboard,file),"utf8"),context);
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  const row=id=>({id,level:"success",icon:"✅",message:"new "+id,ts:"2026-11-28T00:00:00Z",local_time:"00:00"});
  responses.push({cursor:10,rows:[]});
  run("assets/app.js");run("toast.js");run("assets/toast-init.js");
  await flush();assert.equal(get("known").textContent,50);assert.equal(get("timezone").textContent,"Europe/Berlin");assert.match(get("last-heartbeat-exact").textContent,/14:00:00/);assert.equal(intervals.length,1);
  const stack=body.children[0];assert.equal(stack.children.length,0);
  get("countries").children[0].children[0].children[0].events.click();
  assert.equal(get("countries").children[1].hidden,false);
  get("countries").onRender=()=>{window.scrollY=0};
  count=52;responses.push({cursor:12,rows:[row(11),row(12)]});
  await intervals[0]();await flush();
  assert.equal(get("known").textContent,52);assert.equal(get("country-total").textContent,52);
  assert.equal(get("countries").children[1].hidden,false);assert.equal(window.scrollY,240);
  assert.equal(stack.children.length,2);assert.equal(calls.filter(p=>p==="/api/summary").length,2);
  const nodes=[...stack.children], expiry=[...timers.keys()];
  count=53;await get("refresh").events.click();await flush();
  assert.equal(get("known").textContent,53);assert.deepEqual(stack.children,nodes);assert.deepEqual([...timers.keys()],expiry);
  // An event during an outstanding refresh queues one follow-up.
  let release;hold=new Promise(resolve=>{release=resolve});
  const running=get("refresh").events.click();
  count=54;responses.push({cursor:14,rows:[row(13),row(14)]});
  await intervals[0]();await flush();
  assert.equal(calls.filter(p=>p==="/api/summary").length,4);
  hold=null;release();await running;await flush();
  assert.equal(calls.filter(p=>p==="/api/summary").length,5);
  assert.equal(get("known").textContent,54);assert.equal(stack.children.length,4);
  assert.equal(stack.children[3],nodes[1]);assert.ok(expiry.every(id=>timers.has(id)));
  // Disable presentation through the actual shared settings control.
  const enabled=get("toast-settings").children[0].children[0].children[0];
  responses.push({cursor:14,rows:[]});enabled.checked=false;enabled.onchange();await flush();
  assert.equal(stack.children.length,0);
  count=55;responses.push({cursor:15,rows:[row(15)]});await intervals[0]();await flush();
  assert.equal(get("known").textContent,55);assert.equal(stack.children.length,0);
  assert.equal(intervals.length,1);
  zone="Asia/Almaty";
  responses.push({cursor:15,rows:[],timezone:zone,timezone_fallback:false});
  await intervals[0]();await flush();
  assert.equal(get("timezone").textContent,zone);
  assert.match(get("last-heartbeat-exact").textContent,/17:00:00/);
});
