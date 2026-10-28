'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.resolve(__dirname,'../cmd/dh-network/ui/index.html'),'utf8');
const script=html.split('<script>')[1].split('</script>')[0];
const bootstrap=script.indexOf("document.getElementById('export').addEventListener");
assert.ok(bootstrap>0);
function setup(){
 const calls=[],elements={},clicks=[];
 for(const id of ['export','export-preview','export-status','export-copy-status','diagnostic-json-preview','diagnostic-json-text','export-copy',
 'known','online','interval','arp-interval','mdns-hosts','mdns-services','ssdp-hosts','ssdp-services']) {
   elements[id]={textContent:'5',disabled:false,hidden:id==='diagnostic-json-preview',value:'',style:{},
     focus(){calls.push(['focus',id])},select(){calls.push(['select',id])}};
 }
 const buttons=[
  {dataset:{copy:'triggers:\n  - trigger: event.received\n    options:\n      event_type: [tracked_device_absent]',copyLabel:'триггер HA'},
   getAttribute:()=>null},
  {dataset:{copy:'{"event_type":"tracked_device_absent","ip":"192.168.2.30"}',copyLabel:'JSON события'},
   getAttribute:()=>null},
  {dataset:{copy:'device_discovered'},getAttribute:(key)=>key==='title'?'Скопировать event_type':null},
 ];
 for(let i=0;i<buttons.length;i++)buttons[i].addEventListener=(name,fn)=>clicks[i]=fn;
 const body={querySelectorAll:(selector)=>selector==='button[data-copy]'?buttons:[],querySelector:()=>null};
 const toast={hidden:true,textContent:''};
 elements['copy-feedback']=toast;
 const ctx=vm.createContext({
  document:{getElementById:id=>elements[id]||body,body,createElement:()=>({style:{},remove(){},focus(){},select(){}})},
  localStorage:{getItem:()=>null,setItem(){}},
  navigator:{clipboard:{writeText:async value=>{calls.push(['clipboard',value])}}},
  Intl,Date,setTimeout:()=>1,clearTimeout:()=>{}
 });
 vm.runInContext(script.slice(0,bootstrap),ctx);
 return {ctx,clicks,calls,body,elements,toast};
}
test('all event journal copy buttons work without a title and retain multiline JSON/YAML',async()=>{
 const {ctx,clicks,calls,toast}=setup();
 vm.runInContext('enableCellCopy()',ctx);
 assert.equal(clicks.length,3);
 for(const click of clicks)click({stopPropagation(){}});
 await new Promise(resolve=>setImmediate(resolve));
 const values=calls.filter(([kind])=>kind==='clipboard').map(([,value])=>value);
 assert.equal(values.length,3);
 assert.match(values[0],/trigger: event.received/);
 assert.match(values[0],/tracked_device_absent/);
 assert.equal(values[1],'{"event_type":"tracked_device_absent","ip":"192.168.2.30"}');
 assert.equal(values[2],'device_discovered');
 assert.match(toast.textContent,/Скопировано:/);
});
test('diagnostic export is a native Ingress attachment link, not blob URL or fake success',()=>{
 assert.match(html,/<a id="export"[^>]*href="api\/diagnostics\/download"[^>]*target="_blank"/);
 assert.match(html,/id="export-preview"/);
 assert.match(html,/id="diagnostic-json-text"/);
 assert.match(html,/id="export-copy"/);
 assert.doesNotMatch(script,/URL\.createObjectURL/);
 assert.doesNotMatch(script,/Файл .* сформирован\./);
 assert.match(script,/не .*загрузка|запретил загрузку/);
});
test('JSON diagnostic fallback includes view metadata and can be selected manually',async()=>{
 const {ctx,elements,calls}=setup();
 ctx.fetch=async url=>{
   assert.equal(url,'api/diagnostics');
   return {ok:true,json:async()=>({format:'digitalhouses.network.diagnostic.v1',
     debug:{mode:'extended_debug_v1',presence_subscriptions:[{kind:'ip',target:'192.168.2.30'}]}})};
 };
 await vm.runInContext('showDiagnosticPreview()',ctx);
 assert.equal(elements['diagnostic-json-preview'].hidden,false);
 const raw=elements['diagnostic-json-text'].value;
 const report=JSON.parse(raw);
 assert.equal(report.debug.mode,'extended_debug_v1');
 assert.equal(report.browser_view.active_tab,'devices');
 assert.ok(report.browser_view.visible_device_ids);
 await vm.runInContext('copyDiagnosticPreview()',ctx);
 assert.ok(calls.some(([kind,value])=>kind==='clipboard'&&value===raw));
 assert.equal(elements['export-copy-status'].textContent,'Диагностический JSON скопирован.');
});
