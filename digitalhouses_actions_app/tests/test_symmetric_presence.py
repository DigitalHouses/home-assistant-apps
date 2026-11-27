"""Symmetric per-mode settings and migration/ownership regression tests."""
import unittest
from copy import deepcopy
from unittest.mock import patch
from actions import sensor_rules
from actions.binding_store import validate_document
from actions.catalog import CatalogError
from actions.ingress import validate_sensor_assignment
from actions.entity_options import parse_rows,render_rows
import test_presence_modes as fixtures
from test_sensor_engine import SOURCE,TV,motion,state
from test_profiles import SNAP

def mode(enabled=True,data=None,delay=None):
    return {"enabled":enabled,"data":data or {},**({"off_delay_seconds":delay} if delay is not None else {})}

def assignment(eid=TV,day=None,night=None):
    return {"entity_id":eid,"operation":"on","modes":{"day":day or mode(),"night":night or mode()}}

class SymmetricPresenceTests(unittest.TestCase):
    def fixture(self,a,initial="day",auto=True):
        helper=fixtures.PresenceModeTests()
        self.addCleanup(helper.doCleanups)
        h,app,ha,e=helper.build(a,initial,auto)
        return helper,h,app,ha,e

    def test_schema_roundtrip_and_mode_activation_matrix(self):
        a=assignment(day=mode(True,{"brightness_pct":100},300),night=mode(True,{"brightness_pct":20},30))
        b=assignment("light.ceiling",day=mode(True,delay=300),night=mode(False,delay=30))
        c=assignment("light.mirror",day=mode(False),night=mode(True,{"brightness_pct":30},10))
        row={"entity_id":SOURCE,"enabled":True,"assignments":[a,b,c]}
        doc={"schema":1,"rows":[row]}
        self.assertEqual(validate_document(doc),doc)
        self.assertEqual(parse_rows({"switches":render_rows([row])}),[row])
        ids={TV,"light.ceiling","light.mirror"}
        for m,expected in (("day",{TV:100,"light.ceiling":None}),("night",{TV:20,"light.mirror":30}),(None,{})):
            calls=sensor_rules.commands(row,ids,"on",m)
            self.assertEqual({x["target"]["entity_id"][0]:x.get("data",{}).get("brightness_pct") for x in calls},expected)
        self.assertEqual(len(sensor_rules.commands(row,ids,"off","night")),3)
        self.assertEqual(sensor_rules.mode_delay(a,"day"),300)
        self.assertEqual(sensor_rules.mode_delay(a,"night"),30)

    def test_legacy_projection_does_not_change_old_storage(self):
        for old in (fixtures.assignment(TV),
                    fixtures.assignment(TV,"day",{"profile":"day"}),
                    fixtures.assignment(TV,data={"brightness_pct":100},night={"brightness_pct":20}),
                    fixtures.assignment(TV,data={"profile":"current","color_source":"rgb"})):
            row={"entity_id":SOURCE,"enabled":True,"assignments":[old]}
            self.assertEqual(sensor_rules.validate_row(row),row)
            new=assignment(TV,**sensor_rules.mode_blocks(old))
            converted={**row,"assignments":[new]}
            self.assertEqual(sensor_rules.validate_row(converted),converted)
            for m in ("day","night"):
                self.assertEqual(sensor_rules.commands(row,{TV},"on",m),sensor_rules.commands(converted,{TV},"on",m))
                self.assertEqual(sensor_rules.mode_delay(old,m),sensor_rules.mode_delay(new,m))
        independent=assignment(day=mode(True,delay=20),night=mode(True,delay=20))
        self.assertTrue(sensor_rules.mode_allows(independent,None))

    def test_validation_and_disabled_saved_params(self):
        invalid=[{"day":mode()}, {"day":mode(),"night":{"enabled":1,"data":{}}},
                 {"day":mode(),"night":mode(delay=-1)}, {"day":mode(),"night":mode(data={"brightness_pct":101})}]
        for modes in invalid:
            with self.assertRaises(CatalogError):
                sensor_rules.validate_row({"entity_id":SOURCE,"enabled":True,"assignments":[{**assignment(),"modes":modes}]})
        a=assignment(day=mode(),night=mode(False,{"brightness_pct":20}))
        row={"entity_id":SOURCE,"enabled":True,"assignments":[a]}
        validate_sensor_assignment(row,{SOURCE:{"lux_sources":[]}},{TV:{"brightness":False}})
        a["modes"]["night"]["enabled"]=True
        with self.assertRaises(CatalogError):
            validate_sensor_assignment(row,{SOURCE:{"lux_sources":[]}},{TV:{"brightness":False}})

    def test_custom_and_global_are_independent(self):
        a=assignment(day=mode(True,{"profile":"day"},300),night=mode(True,{"brightness_pct":20},30))
        f,h,app,ha,e=self.fixture(a,"night")
        e.changed(SOURCE,motion("on"))
        self.assertEqual(h.run_job(app)[0]["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["data"],{"brightness_pct":20})
        a=assignment(day=mode(True,{"brightness_pct":100}),night=mode(True,{"profile":"night"}))
        f,h,app,ha,e=self.fixture(a,"night")
        e.changed(SOURCE,motion("on"))
        self.assertEqual(h.run_job(app)[0]["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["data"],{"brightness_pct":SNAP["night"]["brightness"]})

    def test_transition_updates_timer_without_restarting_absence(self):
        a=assignment(day=mode(True,delay=300),night=mode(True,delay=30))
        f,h,app,ha,e=self.fixture(a)
        f.activate(h,app,ha,e)
        self.assertEqual(e.owners[TV]["mode"],"day")
        f.transition(app,"night")
        self.assertEqual(e.owners[TV]["mode"],"night")
        self.assertEqual(ha.execute.call_count,1)
        with patch("actions.sensor_engine.time.time",return_value=1000):
            e.changed(SOURCE,motion("off"))
        self.assertEqual(e.owners[TV]["deadline"],1030)
        f.transition(app,"day")
        self.assertEqual(e.owners[TV]["deadline"],1030)
        with patch("actions.sensor_engine.time.time",return_value=1031):
            e.tick()
            self.assertEqual(h.run_job(app)[0]["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["service"],"light.turn_off")

    def test_auto_disabled_retains_activation_timer(self):
        a=assignment(day=mode(True,delay=300),night=mode(True,delay=30))
        f,h,app,ha,e=self.fixture(a,auto=False)
        f.activate(h,app,ha,e)
        f.transition(app,"night")
        with patch("actions.sensor_engine.time.time",return_value=1000):
            e.changed(SOURCE,motion("off"))
        self.assertEqual(e.owners[TV]["deadline"],1300)

    def test_day_only_off_and_night_only_off(self):
        for initial,after in (("day","night"),("night","day")):
            a=assignment(day=mode(initial=="day",delay=10),night=mode(initial=="night",delay=20))
            f,h,app,ha,e=self.fixture(a,initial)
            f.activate(h,app,ha,e)
            f.transition(app,after)
            self.assertEqual(app._jobs.qsize(),1)
            self.assertEqual(h.run_job(app)[0]["state"],"sent")
            self.assertEqual(ha.execute.call_args.args[0]["service"],"light.turn_off")

    def test_distinct_parameters_auto_transition_both_directions(self):
        from datetime import datetime,timezone
        a=assignment(day=mode(True,{"brightness_pct":100},300),night=mode(True,{"brightness_pct":20},30))
        f,h,app,ha,e=self.fixture(a)
        f.activate(h,app,ha,e)
        f.transition(app,"night")
        self.assertEqual(ha.execute.call_args.args[0]["data"],{"brightness_pct":20})
        app._ha_state_changed(TV,state(TV,"on",e.states[TV]["last_changed"],brightness=51,
                         supported_color_modes=["brightness"],color_mode="brightness"))
        ha.read_domain_state.return_value=deepcopy(e.states[TV])
        f.transition(app,"day")
        self.assertEqual(ha.execute.call_args.args[0]["data"],{"brightness_pct":100})
        self.assertEqual(e.owners[TV]["mode"],"day")

    def test_frontend_migration_matches_runtime(self):
        import shutil, subprocess, json
        from pathlib import Path
        if not shutil.which("node"): self.skipTest("Node unavailable")
        js=(Path(__file__).resolve().parents[1]/"rootfs/app/actions/web/app.js").read_text()
        source=js[js.index("function sensorModeBlocks("):js.index("const modeEditors=")]
        for old in (fixtures.assignment(TV),fixtures.assignment(TV,"day",{"profile":"day"}),
                    fixtures.assignment(TV,data={"brightness_pct":100},night={"brightness_pct":20}),
                    fixtures.assignment(TV,data={"profile":"current","color_source":"rgb"})):
            result=subprocess.check_output(["node","-e",source+"\nconsole.log(JSON.stringify(sensorAssignment("+json.dumps(old)+")))"],text=True)
            self.assertEqual(json.loads(result),assignment(TV,**sensor_rules.mode_blocks(old)))
