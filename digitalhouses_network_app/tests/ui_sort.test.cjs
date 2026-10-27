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
 assert.deepEqual(names,['ip','name','mac','presence','sources','last_seen','note']);
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
