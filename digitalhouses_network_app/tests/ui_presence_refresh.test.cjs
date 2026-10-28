'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.resolve(__dirname,'../cmd/dh-network/ui/index.html'),'utf8');
const code=html.split('<script>')[1].split('</script>')[0];
const boot=code.indexOf("document.getElementById('export').addEventListener");
assert.ok(boot>0);
function fixture(){
 const node=()=>({innerHTML:'',textContent:'',hidden:false,style:{},
  querySelectorAll:()=>[],querySelector:()=>null,addEventListener(){}});
 const input=node(),body=node(),filter=node(),menu=node(),overview=node();
 menu.hidden=true;menu.contains=()=>false;
 filter.querySelector=(selector)=>selector==='input'?input:(filter.innerHTML.includes('id="search"')?input:null);
 const all=new Map([['body',body],['filterarea',filter],['presence-menu',menu],['settings-overview',overview]]);
 const document={
   getElementById(id){if(!all.has(id))all.set(id,node());return all.get(id)},
   querySelectorAll:()=>[],
 };
 const copied=[];
 const response={
  status:{database:'ready',poll_interval_seconds:60,scan_interval_seconds:180},
  devices:[
   {id:'a',display_name:'Router',ipv4:'192.168.11.1',mac:'AA:BB:CC:DD:EE:01',presence:'online',last_seen:'2026-10-28T22:32:35Z',note:''},
   {id:'b',display_name:'Phone',ipv4:'192.168.11.58',mac:'AA:BB:CC:DD:EE:02',presence:'online',last_seen:'2026-10-28T22:32:35Z',note:''}
  ],
  'device-sources':[],'mdns-services':[],'ssdp-services':[],'wsd-endpoints':[],
  diagnostics:{counts:{arp_last_scan_hosts:24,arp_hosts:27},ipv4_conflicts:[]},
  presence:[
   {kind:'ip',target:'192.168.11.1',enabled:true,state:'reachable',last_check:'2026-10-28T22:32:35Z',
    last_positive:'2026-10-28T22:32:35Z',last_changed:'',reason:'confirmed_by_arp'},
   {kind:'mac',target:'AA:BB:CC:DD:EE:02',enabled:true,state:'present',last_check:'2026-10-28T22:32:35Z',
    last_positive:'2026-10-28T22:32:35Z',last_changed:'',reason:'confirmed_by_arp'}
  ]
 };
 const requested=[];
 const ctx=vm.createContext({document,Intl,Date,navigator:{},window:{},
  localStorage:{getItem:()=>null,setItem(){}},setTimeout:()=>1,clearTimeout:()=>{},
  fetch:async url=>{requested.push(url);return {ok:true,json:async()=>response[url.replace(/^api\//,'')]}}
 });
 vm.runInContext(code.slice(0,boot),ctx);
 return {ctx,all,body,menu,overview,requested,response};
}
test('actual Devices load fetches persisted Presence and draws green eyes after navigation/reload',async()=>{
 const f=fixture();
 await vm.runInContext('load()',f.ctx);
 assert.ok(f.requested.includes('api/presence'),'Presence not fetched; requests='+JSON.stringify(f.requested)+'; health='+f.all.get('health').textContent+'; body='+f.body.textContent);
 assert.equal((f.body.innerHTML.match(/class="presence-eye"/g)||[]).length,2);
 assert.match(f.body.innerHTML,/192\.168\.11\.1/);
 assert.match(f.body.innerHTML,/AA:BB:CC:DD:EE:02/);
 assert.match(f.body.innerHTML,/28\.10\.2026/);
 await vm.runInContext('load()',f.ctx); // normal 30-second refresh
 assert.equal((f.body.innerHTML.match(/class="presence-eye"/g)||[]).length,2);
 assert.ok(f.requested.filter(x=>x==='api/presence').length>=2);
});
test('IP/MAC popover closes on outside click, stays open on inside click, and closes on Escape',()=>{
 const f=fixture();
 const clickInside={},clickOutside={closest:()=>null},clickTrigger={closest:q=>q==='[data-presence-kind]'?{}:null};
 f.menu.hidden=false;f.menu.contains=target=>target===clickInside;
 vm.runInContext("presenceSelection={kind:'ip',target:'192.168.11.1'}",f.ctx);
 f.ctx.inside={target:clickInside};
 vm.runInContext('handlePresenceOutsideClick(inside)',f.ctx);
 assert.equal(f.menu.hidden,false);
 f.ctx.trigger={target:clickTrigger};
 vm.runInContext('handlePresenceOutsideClick(trigger)',f.ctx);
 assert.equal(f.menu.hidden,false);
 f.ctx.outside={target:clickOutside};
 vm.runInContext('handlePresenceOutsideClick(outside)',f.ctx);
 assert.equal(f.menu.hidden,true);
 assert.equal(vm.runInContext('presenceSelection',f.ctx),null);
 f.menu.hidden=false;
 vm.runInContext("presenceSelection={kind:'mac',target:'AA:BB:CC:DD:EE:02'}",f.ctx);
 vm.runInContext("handlePresenceKeydown({key:'Escape'})",f.ctx);
 assert.equal(f.menu.hidden,true);
});
test('entire old overview with counters, export, diagnostics and Reset now belongs to Settings',()=>{
 const header=html.slice(html.indexOf('<header class="app-header">'),html.indexOf('</header>'));
 const main=html.slice(html.indexOf('<main>'),html.indexOf('</main>'));
 assert.doesNotMatch(header,/class="overview"|id="overview"|id="health"|id="export"|id="reset"/);
 assert.match(main,/<section id="settings-overview" class="settings-overview"[^>]*hidden/);
 for(const id of ['known','online','interval','last-arp','known-arp','ip-conflicts','mdns-hosts',
  'ssdp-hosts','export','export-preview','diagnostic-json-preview','diagnostic-json-text','export-copy',
  'reset','reset-status']){
  assert.match(main,new RegExp('id="'+id+'"'));
 }
 assert.match(code,/settingsOverview\.hidden=page!=='settings'/);
 assert.match(code,/document\.addEventListener\('click',handlePresenceOutsideClick\)/);
 assert.match(code,/document\.addEventListener\('keydown',handlePresenceKeydown\)/);
});
