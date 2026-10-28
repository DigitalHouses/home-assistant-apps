'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.resolve(__dirname,'../cmd/dh-network/ui/index.html'),'utf8');
const script=html.split('<script>')[1].split('</script>')[0];
const bootstrap=script.indexOf("document.getElementById('export').addEventListener");
assert.ok(bootstrap>0);
const page={innerHTML:'',querySelectorAll:()=>[],querySelector:()=>null};
const ctx=vm.createContext({
 document:{getElementById:()=>page,body:{classList:{add(){},remove(){}}}},
 localStorage:{getItem:()=>null,setItem:()=>{}},
 Intl,Date
});
vm.runInContext(script.slice(0,bootstrap),ctx);
test('top navigation contains settings/help and no monitoring YAML tab',()=>{
 const nav=html.slice(html.indexOf('<nav aria-label="Разделы приложения">'),html.indexOf('</nav>'));
 for(const tab of ['devices','sources','events','settings','help'])assert.match(nav,new RegExp('data-page="'+tab+'"'));
 assert.doesNotMatch(nav,/data-page="monitoring"/);
 assert.match(nav,/Журнал событий/);
});
test('contextual address menus expose watches and copy, never per-target intervals',()=>{
 const untracked=vm.runInContext("presenceCellAction('ip','192.168.2.30')",ctx);
 assert.match(untracked,/data-presence-kind="ip"/);
 assert.match(untracked,/data-presence-target="192.168.2.30"/);
 assert.doesNotMatch(untracked,/class="presence-eye"/);
 ctx.subscriptions=[{kind:'mac',target:'E8:FF:1E:D7:3A:48',enabled:true,state:'present',
  last_check:'2026-10-29T12:00:00Z',last_positive:'2026-10-29T12:00:00Z',
  last_changed:'2026-10-29T11:00:00Z',reason:'confirmed_by_arp'}];
 vm.runInContext('presenceSubscriptions=subscriptions',ctx);
 const watched=vm.runInContext("presenceCellAction('mac','E8:FF:1E:D7:3A:48')",ctx);
 assert.match(watched,/class="presence-eye"/);
 assert.match(watched,/2026/);
 assert.match(watched,/data-presence-kind="mac"/);
 assert.equal(vm.runInContext("presenceCellAction('ip','2001:db8::1')",ctx),'');
 assert.match(script,/id="menu-copy"/);
 assert.match(script,/id="menu-presence"/);
 assert.match(script,/id="menu-notify"/);
 assert.doesNotMatch(script,/per-device-interval/);
});
test('friendly Presence name is exposed in menu, watch tooltip and event journal',()=>{
 assert.match(script,/id="menu-name"/);
 assert.match(script,/placeholder="Например, Мой ноутбук"/);
 assert.match(script,/id="menu-save"/);
 assert.match(script,/payload\.label=label/);
 assert.match(script,/data-presence-kind/);
 const tooltip=vm.runInContext("presenceTooltip({label:'Мой ноутбук',state:'reachable',last_check:'',last_positive:'',last_changed:''})",ctx);
 assert.match(tooltip,/Название: Мой ноутбук/);
 assert.match(script,/d\.label\?d\.label\+' · '\+target:target/);
});
test('new subscription displays Working, confirmation counts and exact positive timestamp',()=>{
 ctx.pending=[{kind:'ip',target:'192.168.2.30',enabled:true,state:'working',reason:'scan_requested',
   last_check:'',last_positive:'',last_changed:'',successes:0,failures:0,
   needed_successes:2,needed_failures:3}];
 vm.runInContext('presenceSubscriptions=pending',ctx);
 const working=vm.runInContext("presenceCellAction('ip','192.168.2.30')",ctx);
 assert.match(working,/Working/);
 assert.match(working,/выполняется внеочередное сканирование/);
 assert.match(working,/Нет подтверждений/);
 ctx.pending[0].state='confirming';ctx.pending[0].reason='confirmed_by_arp';
 ctx.pending[0].successes=1;
 ctx.pending[0].last_check='2026-10-29T12:00:01Z';
 const pending=vm.runInContext("presenceCellAction('ip','192.168.2.30')",ctx);
 assert.match(pending,/1 из 2/);
 assert.match(pending,/Подтв\./);
 assert.match(pending,/29\.10\.2026/);
 ctx.device={presence:'online',last_seen:'2026-10-29T12:00:01Z'};
 const online=vm.runInContext('onlineTooltip(device)',ctx);
 assert.match(online,/Последнее положительное подтверждение Online/);
 assert.match(online,/29\.10\.2026/);
 assert.match(online,/12:00:01/);
 assert.match(script,/onlineTooltip\(d\)/);
});
test('HA trigger includes exact registered type, correct entity and selected target',()=>{
 ctx.sample={event_type:'tracked_device_unreachable',
  payload_json:JSON.stringify({event_type:'tracked_device_unreachable',ip:'192.168.2.30'})};
 const snippet=vm.runInContext('eventTemplate(sample)',ctx);
 assert.match(snippet,/trigger: event\.received/);
 assert.match(snippet,/entity_id: event\.dh_network_app_network/);
 assert.match(snippet,/tracked_device_unreachable/);
 assert.match(snippet,/options:/);
 assert.match(snippet,/event_type:/);
});
test('global settings forms include all five scanner intervals and shared hysteresis',()=>{
 for(const key of ['poll_interval_seconds','scan_interval_seconds','mdns_interval_seconds',
  'ssdp_interval_seconds','wsd_interval_seconds','confirm_successes','confirm_failures']){
   assert.match(script,new RegExp(key));
 }
 assert.match(script,/api\/settings/);
 assert.match(script,/api\/presence/);
 assert.match(script,/read\('event-log'\)/);
});
test('help explains green eye, first census and MQTT delivery limitations',()=>{
 vm.runInContext('renderHelp()',ctx);
 assert.match(page.innerHTML,/зелёный глаз/i);
 assert.match(page.innerHTML,/NEW DEVICE/);
 assert.match(page.innerHTML,/Передано MQTT/);
 assert.match(page.innerHTML,/MAC Presence/);
});
