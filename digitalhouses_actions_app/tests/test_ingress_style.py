"""Ingress visual contract: Network-style chrome, full-width Aqara layout."""
from pathlib import Path
from unittest import TestCase

WEB = Path(__file__).resolve().parents[1] / "rootfs/app/actions/web"

class IngressStyleTests(TestCase):
    def test_network_reference_palette_and_header(self):
        html=(WEB/"index.html").read_text()
        css=(WEB/"style.css").read_text()
        for item in ("app-header","brand","app-version","devices-nav","scan"):
            self.assertIn(item,html)
        for color in ("#111b29","#192b41","#284059","#536e83","#137b78","#26b6a5","#82efc7","#ffd094"):
            self.assertIn(color,css)
        self.assertIn("main{padding:14px 22px 22px;width:100%",css)
        self.assertIn(".bindings{display:flex;gap:8px 16px;flex-wrap:wrap",css)
        self.assertNotIn("max-width:1250px",css)

    def test_target_type_icons_and_existing_actions(self):
        js=(WEB/"app.js").read_text()
        for kind in ("switch","rgb","cct","dimmer","bulb"):
            self.assertIn('"'+kind+'"',js)
        self.assertIn('targetIcon(t,id)',js)
        self.assertIn('targetIcon(t,a.entity_id)',js)
        self.assertIn('api("scan",{})',js)
        self.assertIn('api("save",',js)
        self.assertIn('draft.disabled_actions',js)

    def test_import_preserves_raw_document_for_strict_server_validation(self):
        js=(WEB/"app.js").read_text()
        self.assertIn("const documentText=await file.text()",js)
        self.assertIn('JSON.parse(documentText)',js)
        self.assertIn("+documentText+",js)
        self.assertIn("body:raw?data:JSON.stringify(data)",js)

    def test_key_type_and_hold_controls_and_test_callback(self):
        js=(WEB/"app.js").read_text()
        picker=(WEB/"entity_picker.js").read_text()
        self.assertIn('["control_relay","Физическая"],["decoupled","Логическая"]',js)
        self.assertIn('if(logicalPolicy(policy))',js)
        self.assertIn('["ON","ON"],["OFF","OFF"]',js)
        self.assertIn('api("test-light",{entity_id:id})',js)
        self.assertIn("renderTest:lightTestControl",js)
        self.assertIn("if(test)line.append(test)",picker)
        self.assertIn("if(test)row.append(test)",js)

    def test_entire_device_card_is_clickable_and_shows_ha_name(self):
        js=(WEB/"app.js").read_text()
        self.assertIn('a.onclick=()=>open(d)',js)
        self.assertIn('a.tabIndex=0',js)
        self.assertIn('e.key==="Enter"||e.key===" "',js)
        self.assertIn('d.ha_name&&d.ha_name!==d.name',js)
        self.assertIn('deviceTitle(draft)',js)
        self.assertNotIn('button("⚙"',js)

    def test_window_guard_shows_friendly_name_and_entity_id(self):
        js=(WEB/"app.js").read_text()
        self.assertIn('sensor?.name&&sensor.name!==id?sensor.name+" · "+id:id',js)
        self.assertIn('label,"window-guard-name"+(sensor?" muted":" problem")',js)

    def test_climate_editor_uses_advertised_operations_and_temperature(self):
        js=(WEB/"app.js").read_text()
        picker=(WEB/"entity_picker.js").read_text()
        self.assertIn('domains=["light","switch","cover","climate","media_player"]',picker)
        self.assertIn('function climateControls(a,t,row)',js)
        self.assertIn('t.hvac_modes||[]',js)
        self.assertIn('n.min=t.min_temp',js)
        self.assertIn('n.max=t.max_temp',js)
        self.assertIn('n.step=t.target_temp_step',js)

    def test_bound_targets_show_full_domain_and_friendly_name(self):
        import shutil
        import subprocess
        js=(WEB/"app.js").read_text()
        self.assertIn('el("span",targetLabel(id,t),"target-label")',js)
        self.assertRegex(js,r'for\(const t of targets\)\s*\{?\s*x\.append\(targetNode\(t\.entity_id\)\)')
        self.assertIn('const state=target?(liveStates[n.dataset.entity]??target.state):undefined',js)
        if shutil.which("node"):
            source=next(line for line in js.splitlines() if line.startswith("function targetLabel("))
            subprocess.run(["node","-e",source+"""
const assert=require('node:assert/strict');
for(const domain of ['light','switch','cover','climate','media_player','future_domain']){
    const id=domain+'.living_room';
    assert.equal(targetLabel(id,{name:'Зал'}),id+' - Зал');
    assert.equal(targetLabel(id,{name:id}),id);
    assert.equal(targetLabel(id,undefined),id);
}
"""],check=True)

    def test_media_picker_and_volume_editor(self):
        js=(WEB/"app.js").read_text()
        picker=(WEB/"entity_picker.js").read_text()
        self.assertIn('function chooseMedia(a,action)',js)
        self.assertIn('api("browse-media",{entity_id:a.entity_id',js)
        self.assertIn('if(item.can_play)line.append(button("Выбрать"',js)
        self.assertIn('n.min=0;n.max=100;n.step=1;n.value=a.data.volume_pct',js)
        self.assertIn('domains=["light","switch","cover","climate","media_player"]',picker)

    def test_profile_modes_and_fixed_source_selection(self):
        js=(WEB/"app.js").read_text()
        self.assertIn('[["simple","ON/OFF"]]',js)
        self.assertIn('["fixed","Фиксированные"],["current","День/Ночь"]',js)
        self.assertIn('[["day","День"],["night","Ночь"],["custom","Свои"]]',js)
        self.assertIn('if(profileSelect(a,t,p,action))',js)
        self.assertIn('if(!(t.brightness||t.cct||t.rgb)&&!Object.keys(a.data).length)return',js)
        self.assertIn('if(a.operation==="volume"&&profileSelect(a,t,p,action,true))',js)

    def test_minutes_seconds_duration_controls(self):
        import shutil
        import subprocess
        js=(WEB/"app.js").read_text()
        self.assertIn('durationControl("Авто-OFF после включения",draft.relay_timers?.[key],1',js)
        self.assertIn('durationControl(editing?.sensor?"Авто-OFF после отсутствия":"Авто-OFF после включения",a.off_delay_seconds,editing?.sensor?0:1',js)
        self.assertIn('formatDuration(t.off_delay_seconds)',js)
        self.assertIn('formatDuration(a.off_delay_seconds)',js)
        self.assertIn('formatDuration(remaining)',js)
        self.assertIn('main.querySelector(".duration-control input:invalid")',js)
        if not shutil.which("node"):
            self.skipTest("Node unavailable")
        source=js[js.index("function formatDuration("):js.index("function modeControls(")]
        subprocess.run(["node","-e",source+"""
const assert=require('node:assert/strict');
for(const n of [0,1,59,60,61,90,1800,1830,86399,86400]){
  const [m,s]=splitDuration(n);
  assert.equal(joinDuration(m,s,0),n);
}
assert.deepEqual(splitDuration(undefined),['','']);
assert.equal(joinDuration('','',1),undefined);
assert.equal(joinDuration('30','',1),1800);
assert.equal(joinDuration('','45',1),45);
assert.equal(joinDuration('0','0',0),0);
assert.equal(formatDuration(1830),'30 мин. 30 сек.');
for(const args of [['0','0',1],['1','60',0],['1440','1',0],['-1','0',0],['1.5','0',0],['1e2','0',0],['','-1',0]]){
  assert.throws(()=>joinDuration(...args));
}
function el(tag,text,cls){
  return {tag,textContent:text,className:cls,value:'',children:[],validity:{badInput:false},
    append(...c){this.children.push(...c)},setAttribute(){},setCustomValidity(v){this.error=v}};
}
function button(text,fn,cls){const b=el('button',text,cls);b.onclick=fn;return b}
function update(){}
const document={createTextNode:v=>v};
let result=1830;
const control=durationControl('Авто-OFF',result,1,v=>result=v);
const m=control.children[1].children[0],s=control.children[2].children[0],clear=control.children[3];
assert.equal(m.value,'30');assert.equal(s.value,'30');
m.value='2';m.oninput();assert.equal(result,150);
s.value='60';s.oninput();assert.equal(result,150);assert.ok(s.error);
s.value='15';s.oninput();assert.equal(result,135);assert.equal(s.error,'');
clear.onclick();assert.equal(result,undefined);assert.equal(m.value,'');assert.equal(s.value,'');
"""],check=True)

    def test_schedule_editor_uses_existing_assignment_picker(self):
        js=(WEB/"app.js").read_text()
        html=(WEB/"index.html").read_text()
        self.assertIn('id="schedules-nav"',html)
        self.assertIn('function renderScheduleEdit()',js)
        self.assertIn('["time","Время"],["sunrise","Рассвет"],["sunset","Закат"]',js)
        self.assertIn('n.min=-720;n.max=720;n.step=1',js)
        self.assertIn('for(const a of existing)assignedRow(action,a,main)',js)
        self.assertIn('api("save-schedule",{revision:draft.revision,config})',js)
        self.assertIn('api("delete-schedule",{revision:draft.revision,entity_id:draft.id})',js)

    def test_common_action_editor_reuses_assignment_editor(self):
        js=(WEB/"app.js").read_text()
        html=(WEB/"index.html").read_text()
        self.assertIn('id="common-nav"',html)
        self.assertIn('function renderCommonList()',js)
        self.assertIn('function appendCommonChoice(container,action)',js)
        self.assertIn('api("run-common",{entity_id:common.entity_id})',js)
        self.assertIn('api("save-common",{revision:draft.revision,config})',js)
        self.assertIn('api("delete-common",{revision:draft.revision,entity_id:draft.id})',js)
