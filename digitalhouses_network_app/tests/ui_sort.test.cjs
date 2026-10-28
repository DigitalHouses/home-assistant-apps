'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(
  path.resolve(__dirname, '../cmd/dh-network/ui/index.html'), 'utf8'
);
const start = html.indexOf('<script>') + 8;
const end = html.indexOf('</script>', start);
assert.ok(start >= 8 && end > start, 'Embedded Ingress JS exists');
const script = html.slice(start, end);
const bootstrap = script.indexOf("document.getElementById('export').addEventListener");
assert.ok(bootstrap > 0, 'Bootstrap is separated from pure sort and view helpers');

const view = { innerHTML: '', querySelectorAll: () => [], querySelector: () => null };
const ctx = vm.createContext({
  document: { getElementById: () => view },
  Intl, Date,
});
vm.runInContext(script.slice(0, bootstrap), ctx);

const sample = [
 { id:'ten', ipv4:'192.168.11.10', display_name:'Ten', mac:'02:00:00:00:00:0A',presence:'online',last_seen:'2026-10-27T11:00:00Z',note:'beta' },
 { id:'blank', ipv4:'', display_name:'None', mac:'02:00:00:00:00:FF',presence:'not_observed',last_seen:'',note:'' },
 { id:'two', ipv4:'192.168.11.2', display_name:'Two', mac:'02:00:00:00:00:02',presence:'online',last_seen:'2026-10-27T12:00:00Z',note:'alpha' },
 { id:'thirty', ipv4:'192.168.11.30', display_name:'Thirty', mac:'02:00:00:00:00:1E',presence:'online',last_seen:'2026-10-27T10:00:00Z',note:'' },
];
ctx.__devices = sample;
vm.runInContext('devices=__devices',ctx);

function setSort(key, direction) { vm.runInContext("sortKey='"+key+"';sortDirection='"+direction+"'",ctx) }
function rows() { return Array.from(vm.runInContext('visibleDeviceIDs()',ctx)) }
function htmlForSources(id) { return vm.runInContext("sourcesForDisplay('"+id+"')",ctx) }

test('numeric IPv4 ascending, missing addresses last', () => {
 setSort('ip','asc');
 assert.deepEqual(rows(),['two','ten','thirty','blank']);
});
test('numeric IPv4 descending, missing addresses still last', () => {
 setSort('ip','desc');
 assert.deepEqual(rows(),['thirty','ten','two','blank']);
});
test('all seven headers allow sorting and keep selected ARIA direction', () => {
 const names=Array.from(vm.runInContext('deviceColumns.map(x=>x[0])',ctx));
 assert.deepEqual(names,['name','ip','mac','presence','sources','last_seen','note']);
 assert.match(vm.runInContext('sortedHeaders()',ctx),/^<th scope="col" class="index-col"[^>]*>№<\/th>/);
 for(const key of names){
  setSort(key,'asc');
  assert.equal(rows().length,4,key);
  assert.match(vm.runInContext('sortedHeaders()',ctx), /aria-sort="ascending"/);
 }
});
test('Note and last online sort with missing values at the bottom', () => {
 setSort('note','asc');
 assert.deepEqual(rows().slice(0,2),['two','ten']);
 setSort('last_seen','desc');
 assert.deepEqual(rows().slice(0,3),['two','ten','thirty']);
 assert.equal(rows().at(-1),'blank');
});
test('sort button toggles between ascending and descending', () => {
 setSort('ip','asc');
 vm.runInContext("changeSort('ip')",ctx);
 assert.deepEqual(rows(),['thirty','ten','two','blank']);
 vm.runInContext("changeSort('ip')",ctx);
 assert.deepEqual(rows(),['two','ten','thirty','blank']);
});
test('Bonjour details exist only in a badge hover, not a table column', () => {
 ctx.__origins=[{device_id:'two',source:'ARP',last_reported_at:'2026-10-27T12:00:00Z'},
  {device_id:'two',source:'mDNS',reference:'aqara.local',last_reported_at:'2026-10-27T12:00:00Z'}];
 ctx.__services=[{device_id:'two',instance:'Aqara Hub',type:'_aqara._tcp.local',port:43372,target:'aqara.local'},
  {device_id:'two',instance:'Matter',type:'_matter._tcp.local',port:5540,target:'aqara.local'}];
 vm.runInContext('origins=__origins;mdnsServices=__services',ctx);
 const badge=htmlForSources('two');
 assert.match(badge,/mDNS · 2/);
 assert.match(badge,/_matter\._tcp\.local/);
 assert.match(badge,/43372/);
 assert.match(badge,/title="/);
 assert.doesNotMatch(vm.runInContext('sortedHeaders()',ctx),/Bonjour сервисы/);
});
test('filter and export IDs follow the on-screen order', () => {
 setSort('ip','asc');
 vm.runInContext("filter='192.168.11.'",ctx);
 assert.deepEqual(rows(),['two','ten','thirty']);
 assert.match(script,/visible_device_ids:shown/);
 assert.match(script,/sort_column:selectedTab==='devices'\?sortKey:null/);
 assert.match(script,/sort_direction:selectedTab==='devices'\?sortDirection:null/);
});

test('genuine discovered names only: all MAC forms and unknown placeholders are hidden', () => {
 const functionCall=(value,mac)=>vm.runInContext('recognizableName('+JSON.stringify(value)+','+JSON.stringify(mac)+')',ctx);
 assert.equal(functionCall('E8:FF:1E:D7:38:17','E8:FF:1E:D7:38:17'),'');
 assert.equal(functionCall('04-92-26-53-9c-b4','04:92:26:53:9C:B4'),'');
 assert.equal(functionCall('54ef44a716c9','18:C2:3C:7B:AF:41'),'');
 assert.equal(functionCall('54ef44a716c9.local','18:C2:3C:7B:AF:41'),'');
 assert.equal(functionCall('unknown','02:00:00:00:00:01'),'');
 assert.equal(functionCall('ff5aa64b3dea4021acaea16660e7c6b9.local','02:7F:2F:27:4E:92'),'');
 assert.equal(functionCall('VIEW71','18:31:BF:2F:ED:37'),'VIEW71');
 assert.equal(functionCall('Apple-TV-ZAL','C8:69:CD:34:9F:0A'),'Apple-TV-ZAL');
 assert.equal(functionCall('xzg.local','24:DC:C3:E2:6E:17'),'xzg');
 assert.equal(functionCall('13ProMAX-SKY','88:B9:45:80:A7:55'),'13ProMAX-SKY');
});
test('visible names drive name sorting, missing genuine names stay at the end', () => {
 ctx.__devices=sample.concat([
  {id:'mac-as-name',ipv4:'192.168.11.11',display_name:'02:11:22:33:44:55',mac:'02:11:22:33:44:55',hostname:'',presence:'online',last_seen:'',note:''},
  {id:'bonjour-mac-only',ipv4:'192.168.11.12',display_name:'54ef44a716c9',mac:'18:C2:3C:7B:AF:41',hostname:'54ef44a716c9.local',presence:'online',last_seen:'',note:'sample'}
 ]);
 vm.runInContext("devices=__devices;filter='';sortKey='name';sortDirection='asc'",ctx);
 assert.equal(rows().at(-2)==='mac-as-name'||rows().at(-2)==='bonjour-mac-only',true);
 assert.deepEqual(rows().slice(0,4),['blank','ten','thirty','two']);
 vm.runInContext('renderTable()',ctx);
 assert.doesNotMatch(view.innerHTML,/class="name-value"[^>]*>02:11:22:33:44:55<\/strong>/);
 assert.doesNotMatch(view.innerHTML,/class="name-value"[^>]*>54ef44a716c9<\/strong>/);
 assert.match(view.innerHTML,/class="name-cell"><strong class="name-value" title="">—<\/strong>/);
 ctx.__devices=sample;
 vm.runInContext('devices=__devices',ctx);
});
test('row numbers are sequential and react to sorting and filtering', () => {
 vm.runInContext("filter='';sortKey='ip';sortDirection='asc';renderTable()",ctx);
 const htmlAsc=view.innerHTML;
 const numbers=Array.from(htmlAsc.matchAll(/class="num-cell">(\d+)<\/td>/g),x=>Number(x[1]));
 assert.deepEqual(numbers,[1,2,3,4]);
 assert.match(htmlAsc,/class="num-cell">1<\/td><td class="name-cell">/);
 assert.ok(htmlAsc.indexOf('>192.168.11.2<')<htmlAsc.indexOf('>192.168.11.10<'));
 vm.runInContext("filter='192.168.11.30';renderTable()",ctx);
 assert.deepEqual(Array.from(view.innerHTML.matchAll(/class="num-cell">(\d+)<\/td>/g),x=>Number(x[1])),[1]);
 assert.match(script,/displayed_columns:selectedTab==='devices'\?\['№',\.\.\.deviceColumns/);
 vm.runInContext("filter='';sortKey='ip';sortDirection='asc'",ctx);
});
test('Note is either a compact Add button or the note itself, with safe one-line tooltip', () => {
 const filled=vm.runInContext("noteAction({id:'noted',note:'apple-ТВ'})",ctx);
 assert.match(filled,/class="note-action note-filled"/);
 assert.match(filled,/>apple-ТВ<\/button>/);
 assert.doesNotMatch(filled,/>Изменить<\/button>/);
 const empty=vm.runInContext("noteAction({id:'empty',note:''})",ctx);
 assert.match(empty,/class="note-action note-empty"/);
 assert.match(empty,/>Добавить<\/button>/);
 const longNote=vm.runInContext("noteAction({id:'safe',note:'<script>bad</script> \"long\"'})",ctx);
 assert.doesNotMatch(longNote,/<script>/);
 assert.match(longNote,/&lt;script&gt;bad&lt;\/script&gt;/);
 assert.match(longNote,/&quot;long&quot;/);
 assert.match(longNote,/title="Редактировать заметку:/);
 assert.match(html,/\.devices-table td\.note-cell \.note-action\{[^}]*text-overflow:ellipsis/);
});

test('compact single header keeps navigation visible and all cards collapsed by default', () => {
 const headerStart=html.indexOf('<header class="app-header">');
 const headerEnd=html.indexOf('</header>',headerStart);
 const main=html.indexOf('<main>',headerEnd);
 assert.ok(headerStart>0 && headerEnd>headerStart && main>headerEnd);
 const header=html.slice(headerStart,headerEnd);
 assert.match(header, /<h1>DigitalHouses Network App<\/h1>/);
 assert.match(header, /<nav aria-label="Разделы приложения">/);
 for (const tab of ['devices','sources','events']) {
  assert.match(header,new RegExp('data-page="'+tab+'"'));
 }
 assert.match(header, /<details id="overview" class="overview">/);
 assert.doesNotMatch(header, /<details[^>]*\sopen(?:\s|=|>)/);
 assert.match(header, /<summary[^>]*>.*?Показатели.*?<span id="health"/s);
 assert.equal((header.match(/class="stat"/g)||[]).length,11);
 assert.match(header, /id="export"/);
 assert.match(header, /id="export-status"/);
 assert.match(header, /Online \(ARP \/ HA, не ping\)/);
 assert.match(header, /Online не означает ответ на ICMP ping/);
 assert.doesNotMatch(html.slice(main,html.indexOf('<script>',main)),/class="stat"/);
 assert.match(html, /\.overview-panel\{position:absolute;/);
 assert.match(html, /\.overview summary:focus-visible\{/);
});
test('metrics dropdown is compact and does not contain orange notice or chat request', () => {
 const header=html.slice(html.indexOf('<header class="app-header">'),html.indexOf('</header>'));
 assert.match(header,/Online не означает ответ на ICMP ping/);
 assert.doesNotMatch(header,/<div class="notice">/);
 assert.match(header,/id="export"/);
 assert.doesNotMatch(html,/Пришли его в чат для анализа/);
 assert.match(script,/message.textContent='Файл '\+file\+' сформирован\.'/);
 assert.match(script,/ICMP ping не выполняется/);
 assert.equal(vm.runInContext('deviceColumns[3][1]',ctx),'Наблюдение');
});
test('search is immediately to the right of device count, in the same flex row', () => {
 const main=html.slice(html.indexOf('<main>'),html.indexOf('</main>'));
 assert.match(main,/<div id="devices-tools" class="devices-tools" hidden><h2 id="devices-count">Устройства \(—\)<\/h2><div id="filterarea"><\/div><\/div>/);
 assert.match(html,/\.devices-tools\{display:flex;align-items:center;/);
 assert.match(html,/\.devices-tools\[hidden\]\{display:none\}/);
 assert.match(script,/devicesCount.textContent='Устройства \('\+found.length\+'\)'/);
 assert.match(script,/devicesTools.hidden=false/);
 assert.match(script,/devicesTools.hidden=true/);
 assert.doesNotMatch(script,/body.innerHTML='<h2>Устройства/);
 vm.runInContext("filter='192.168.11.30';renderTable()",ctx);
 assert.equal(view.textContent,'Устройства (1)');
 assert.match(view.innerHTML,/192.168.11.30/);
 vm.runInContext("filter='';renderTable()",ctx);
 assert.equal(view.textContent,'Устройства (4)');
});
