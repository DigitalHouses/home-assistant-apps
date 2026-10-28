'use strict';

const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(path.resolve(__dirname,'../cmd/dh-network/ui/index.html'),'utf8');
const script=html.split('<script>')[1].split('</script>')[0];
const bootstrap=script.indexOf("document.getElementById('export').addEventListener");
assert.ok(bootstrap>0);
const contents={};
const listeners={};
const body={
 innerHTML:'',textContent:'',hidden:false,
 querySelector:()=>null,
 querySelectorAll:()=>[],
 classList:{add:()=>{},remove:()=>{}}
};
const toast={hidden:true,textContent:''};
const storage=new Map();
const localStorage={
 getItem:k=>storage.has(k)?storage.get(k):null,
 setItem:(k,v)=>storage.set(k,String(v))
};
const ctx=vm.createContext({
 document:{getElementById:id=>id==='copy-feedback'?toast:body,body,createElement:()=>({style:{},focus(){},select(){},remove(){}})},
 window:{addEventListener(){},removeEventListener(){}},
 localStorage,Intl,Date,navigator:{},clearTimeout:()=>{},setTimeout:()=>1
});
vm.runInContext(script.slice(0,bootstrap),ctx);
const watches=[{
 id:'a',display_name:'U7 Pro 1 floor U7 Pro 1 floor',
 ipv4:'192.168.2.2',mac:'8C:30:66:70:22:6C',presence:'online',
 last_seen:'2026-10-28T18:00:00Z',note:'Отдельный этаж'
}];
ctx.watchData=watches;
vm.runInContext('devices=watchData',ctx);

test('all seven columns are resizeable, with fixed colgroup and accessible resize handles',()=>{
 vm.runInContext('renderTable()',ctx);
 const source=body.innerHTML;
 assert.equal((source.match(/class="col-resizer"/g)||[]).length,7);
 assert.match(source,/<colgroup><col style="width:42px">/);
 assert.match(source,/data-column="name"/);
 assert.match(source,/role="separator" aria-orientation="vertical" tabindex="0"/);
 assert.match(source,/aria-label="Ширина колонки Имя"/);
 assert.match(html,/\.devices-table\{table-layout:fixed/);
 assert.match(html,/\.grid-scroll\{overflow-x:auto/);
});
test('column sizing clamps extremes, survives refresh, and persists without server writes',()=>{
 vm.runInContext("updateColumnWidth('name',450)",ctx);
 assert.equal(vm.runInContext('columnWidths.name',ctx),450);
 assert.equal(JSON.parse(storage.get('dh-network-device-column-widths-v1')).name,450);
 vm.runInContext('renderTable()',ctx);
 assert.match(body.innerHTML,/data-column="name" style="width:450px"/);
 vm.runInContext('columnWidths=loadColumnWidths()',ctx);
 assert.equal(vm.runInContext('columnWidths.name',ctx),450);
 vm.runInContext("updateColumnWidth('name',-900)",ctx);
 assert.equal(vm.runInContext('columnWidths.name',ctx),110);
 vm.runInContext("updateColumnWidth('name',9000)",ctx);
 assert.equal(vm.runInContext('columnWidths.name',ctx),1000);
 vm.runInContext("updateColumnWidth('name',230)",ctx);
 assert.equal(vm.runInContext('columnWidths.name',ctx),230);
});
test('invalid saved widths are safely ignored and reset to defaults',()=>{
 storage.set('dh-network-device-column-widths-v1','{not-json');
 vm.runInContext('columnWidths=loadColumnWidths()',ctx);
 assert.equal(vm.runInContext('columnWidths.name',ctx),230);
 storage.set('dh-network-device-column-widths-v1',JSON.stringify({name:'NaN',ip:190,evil:9999}));
 vm.runInContext('columnWidths=loadColumnWidths()',ctx);
 assert.equal(vm.runInContext('columnWidths.name',ctx),230);
 assert.equal(vm.runInContext('columnWidths.ip',ctx),190);
 assert.equal(vm.runInContext('columnWidths.evil',ctx),undefined);
 vm.runInContext("updateColumnWidth('ip',116)",ctx);
});
test('duplicate whole-name echoes are collapsed only in UI projection',()=>{
 const name=vm.runInContext('visibleDeviceName(watchData[0])',ctx);
 assert.equal(name,'U7 Pro 1 floor');
 assert.equal(watches[0].display_name,'U7 Pro 1 floor U7 Pro 1 floor');
 assert.equal(vm.runInContext("recognizableName('Living Livingroom', '')",ctx),'Living Livingroom');
 assert.equal(vm.runInContext("recognizableName('Home Assistant Prod Home Assistant Prod','')",ctx),'Home Assistant Prod');
});
test('copy actions remain for name and Note while IP/MAC move into address menus',()=>{
 vm.runInContext('renderTable()',ctx);
 assert.match(body.innerHTML,/data-copy="U7 Pro 1 floor"/);
 assert.match(body.innerHTML,/data-presence-target="192.168.2.2"/);
 assert.match(body.innerHTML,/data-presence-target="8C:30:66:70:22:6C"/);
 assert.match(body.innerHTML,/data-copy="Отдельный этаж"/);
 assert.match(body.innerHTML,/class="copy-action"/);
 assert.match(body.innerHTML,/aria-label="Параметры IP 192.168.2.2"/);
 const malicious=vm.runInContext("copyAction('<script>\\\"&', 'IP')",ctx);
 assert.doesNotMatch(malicious,/<script>/);
 assert.match(malicious,/&lt;script&gt;/);
 assert.match(malicious,/&quot;/);
 assert.match(malicious,/&amp;/);
});
test('empty cells have no copy button, Note editor remains available',()=>{
 const empty=vm.runInContext("copyAction('', 'имя')",ctx);
 assert.equal(empty,'');
 assert.equal(vm.runInContext("copyAction('—','IP')",ctx),'');
 assert.match(body.innerHTML,/class="note-action note-filled"/);
 assert.match(body.innerHTML,/data-id="a"/);
 assert.match(html,/\.devices-table td:hover \.copy-action/);
 assert.match(html,/@media\(hover:none\)\{\.devices-table \.copy-action\{opacity:1\}/);
});
test('clipboard API confirms success with accessible live status',async()=>{
 let result='';
 ctx.navigator={clipboard:{writeText:async value=>{result=value}}};
 const ok=await vm.runInContext("copyText('192.168.2.2','IP')",ctx);
 assert.equal(ok,true);
 assert.equal(result,'192.168.2.2');
 assert.equal(toast.hidden,false);
 assert.equal(toast.textContent,'Скопировано: IP');
 assert.match(html,/id="copy-feedback"[^>]*role="status" aria-live="polite"/);
});
test('clipboard failure falls back to legacy copy without changing server state',async()=>{
 const actions=[];
 const mock={
  value:'',readOnly:false,style:{},focus:()=>actions.push('focus'),
  select:()=>actions.push('select'),remove:()=>actions.push('remove')
 };
 ctx.navigator={clipboard:{writeText:async()=>{throw Error('denied')}}};
 ctx.document.createElement=()=>mock;
 ctx.document.body.appendChild=()=>actions.push('append');
 ctx.document.execCommand=cmd=>{actions.push(cmd);return true};
 const ok=await vm.runInContext("copyText('192.168.2.33','IP')",ctx);
 assert.equal(ok,true);
 assert.equal(mock.value,'192.168.2.33');
 assert.deepEqual(actions,['append','focus','select','copy','remove']);
});
