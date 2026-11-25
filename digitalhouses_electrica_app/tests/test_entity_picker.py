"""Entity Picker: HA catalogue metadata and actual JS selection logic."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from electrica.ingress_catalog import target_catalog
from test_ingress import PROFILE, REGISTRIES, STATES
from copy import deepcopy

WEB = Path(__file__).resolve().parents[1] / "rootfs/app/electrica/web"

class EntityPickerTests(unittest.TestCase):
    def test_registry_metadata_and_protected_input(self):
        devices, areas, entities = deepcopy(REGISTRIES)
        devices[1]["name"]="Hardware"
        devices[1]["name_by_user"]="My hardware"
        entities[2]["platform"]="mqtt"
        catalog=target_catalog((devices,areas,entities),STATES,PROFILE)
        rgb=catalog["light.rgb"]
        self.assertEqual(rgb["domain"],"light")
        self.assertEqual(rgb["area_id"],"living")
        self.assertEqual(rgb["integration"],"mqtt")
        self.assertEqual(rgb["device_name"],"My hardware")
        self.assertNotIn("switch.input_relay",catalog)

    def test_javascript_filters_and_lossless_selection(self):
        if not shutil.which("node"):
            self.skipTest("Node unavailable")
        code = r"""
const assert=require("node:assert/strict");
require(process.argv[1]);
const p=globalThis.DHElectricaEntityPicker;
const a={entity_id:"light.a",name:"Люстра",area:"Гостиная",area_id:"living",
         device_name:"Panel",integration:"mqtt",state:"on",domain:"light"};
const b={entity_id:"switch.b",name:"Реле",area:"Спальня",area_id:"bedroom",
         integration:"esphome",state:"unavailable",domain:"switch"};
const c={entity_id:"light.c",name:"Без комнаты",state:"off"};
const items=[a,b,c];
const f={domains:["light","switch"],domain:p.ALL,area:p.ALL,
         integration:p.ALL,availability:p.ALL,query:""};
assert.equal(p.resolveArea(items,"living","Спальня"),"living");
assert.equal(p.resolveArea(items,"deleted","Гостиная"),p.ALL);
assert.equal(p.resolveArea(items,null,"Спальня"),"bedroom");
assert.equal(p.matches(a,{...f,query:"panel"}),true);
assert.equal(p.matches(a,{...f,query:"MQTT"}),true);
assert.equal(p.matches(b,{...f,area:"living"}),false);
assert.equal(p.matches(c,{...f,area:p.NONE}),true);
assert.equal(p.matches(b,{...f,domain:"light"}),false);
assert.equal(p.matches(b,{...f,availability:"unavailable"}),true);
assert.equal(p.matches(b,{...f,integration:"mqtt"}),false);
const v=p.displayed(items,new Set(["switch.b","light.missing"]),{...f,area:"living"});
assert.deepEqual(v.rows.map(x=>x.entity_id),["switch.b","light.missing","light.a"]);
assert.equal(v.rows[1].missing,true);
assert.equal(v.outside.has("switch.b"),true);
const old=[{entity_id:"light.a",operation:"on",data:{rgb_color:[1,2,3],brightness_pct:60}},
           {entity_id:"light.missing",operation:"off",data:{}}];
const merged=p.mergeAssignments(old,["light.missing","light.a","switch.b"]);
assert.deepEqual(merged,[old[1],old[0],{entity_id:"switch.b",operation:"toggle",data:{}}]);
assert.equal(p.displayed(Array.from({length:200},(_,i)=>({...a,entity_id:"light."+i})),new Set(["light.199"]),f).rows.length,151);
"""
        subprocess.run(["node","-e",code,str(WEB/"entity_picker.js")],check=True)

    def test_ingress_uses_single_picker_and_serves_script(self):
        html=(WEB/"index.html").read_text()
        js=(WEB/"app.js").read_text()
        self.assertLess(html.index('src="entity_picker.js"'),html.index('src="app.js"'))
        self.assertIn("DHElectricaEntityPicker.open",js)
        self.assertIn("DHElectricaEntityPicker.mergeAssignments",js)
        self.assertNotIn("showSwitch",js)
        self.assertNotIn("Поиск светильников / реле",js)
