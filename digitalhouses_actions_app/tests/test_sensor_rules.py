import unittest
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from actions import sensor_rules
from actions.binding_store import validate_document
from actions.catalog import CatalogError
from actions.entity_options import project,parse_rows,render_rows
from actions.ingress import validate_sensor_assignment,save_sensor,revision
from test_ingress import PROFILE,REGISTRIES,STATES,KEY
from actions.ingress_catalog import target_catalog
from types import SimpleNamespace
from unittest.mock import Mock
import threading

S="binary_sensor.room_presence"
L="sensor.room_illuminance"
A={"entity_id":"light.rgb","operation":"on","data":{"profile":"current","color_source":"rgb"},"off_delay_seconds":60}
ROW={"entity_id":S,"enabled":True,"lux_entity_id":L,"lux_threshold":70,"assignments":[A]}

def states(now):
    def s(eid,value,cls,**attrs):
        return {"entity_id":eid,"state":value,"last_updated":now.isoformat(),"attributes":{"device_class":cls,**attrs}}
    return [s(S,"off","occupancy",friendly_name="Присутствие"),
            s(L,"35","illuminance",unit_of_measurement="lx"),
            s("sensor.raw","35","illuminance",unit_of_measurement="raw"),
            s("sensor.other","20","illuminance",unit_of_measurement="lx"),
            s("binary_sensor.window","off","window")]

REG=([{"id":"dev","area_id":"living"},{"id":"other"}],[{"area_id":"living","name":"Зал"}],
     [{"entity_id":x,"device_id":"other" if x=="sensor.other" else "dev","platform":"mqtt"}
      for x in [S,L,"sensor.raw","sensor.other","binary_sensor.window"]])

class SensorTests(unittest.TestCase):
    def test_only_confirmed_presence_and_same_device_lux(self):
        now=datetime.now(timezone.utc)
        catalog=sensor_rules.discover(REG,states(now))
        self.assertEqual(set(catalog),{S})
        self.assertEqual(catalog[S]["name"],"Присутствие")
        self.assertEqual(catalog[S]["area"],"Зал")
        self.assertEqual([x["entity_id"] for x in catalog[S]["lux_sources"]],[L])

    def test_lux_gate_does_not_guess(self):
        now=datetime.now(timezone.utc)
        by_id={s["entity_id"]:s for s in states(now)}
        self.assertTrue(sensor_rules.lux_allows(ROW,by_id,now))
        self.assertFalse(sensor_rules.lux_allows({**ROW,"lux_threshold":35},by_id,now))
        self.assertFalse(sensor_rules.lux_allows({**ROW,"lux_threshold":0},by_id,now))
        self.assertFalse(sensor_rules.lux_allows(ROW,by_id,now+timedelta(minutes=16)))
        self.assertFalse(sensor_rules.lux_allows(ROW,{},now))
        self.assertTrue(sensor_rules.lux_allows({"entity_id":S},by_id,now))
        by_id[L]["state"]="unavailable"
        self.assertFalse(sensor_rules.lux_allows(ROW,by_id,now))

    def test_same_document_preserves_keys_and_sensor_assignments(self):
        old={"entity_id":KEY,"enabled":True,"actions":{"single":["light.bra"]}}
        document={"schema":1,"rows":[old,ROW]}
        self.assertEqual(validate_document(document),document)
        options={"switches":render_rows(document["rows"]),"_bindings_store":True}
        self.assertEqual(parse_rows(options),document["rows"])
        projected=project(PROFILE,options)
        self.assertEqual(projected["sensor_bindings"],{S:ROW})
        self.assertEqual(projected["rooms"][0]["switches"][0]["bindings"]["single"]["targets"],["light.bra"])
        self.assertEqual(projected["orphan_bindings"],[])
        self.assertEqual(sensor_rules.commands(ROW,{"light.rgb"},"on"),[{
            "service":"light.turn_on","target":{"entity_id":["light.rgb"]},"data":{"profile":"current","color_source":"rgb"}}])
        self.assertEqual(sensor_rules.commands(ROW,{"light.rgb"},"off"),[{
            "service":"light.turn_off","target":{"entity_id":["light.rgb"]}}])

    def test_invalid_sensor_config(self):
        cases=[{**ROW,"enabled":"true"},{**ROW,"lux_threshold":-1},{**ROW,"assignments":[{**A,"operation":"toggle"}]},
               {**ROW,"assignments":[{**A,"off_delay_seconds":-1}]},{**ROW,"assignments":[A,A]}]
        for bad in cases:
            with self.assertRaises(CatalogError):sensor_rules.validate_row(bad)
        sources=sensor_rules.discover(REG,states(datetime.now(timezone.utc)))
        targets=target_catalog(REGISTRIES,STATES,PROFILE)
        validate_sensor_assignment(ROW,sources,targets)
        with self.assertRaises(CatalogError):validate_sensor_assignment({**ROW,"lux_entity_id":"sensor.other"},sources,targets)
        with self.assertRaises(CatalogError):validate_sensor_assignment({k:v for k,v in ROW.items() if not k.startswith("lux_")},sources,targets)

    def test_save_sensor_keeps_keys(self):
        old={"entity_id":KEY,"enabled":True,"actions":{"single":["light.bra"]}}
        opts={"switches":render_rows([old]),"_bindings_store":True}
        app=SimpleNamespace(options=Mock(),config=project(PROFILE,opts),
             _mutex=threading.RLock(),_scan_lock=threading.Lock(),
             sensor_catalog=sensor_rules.discover(REG,states(datetime.now(timezone.utc))),
             target_catalog=target_catalog(REGISTRIES,STATES,PROFILE))
        app.options.read.return_value=opts
        save_sensor(app,{"revision":revision([old]),"config":ROW})
        self.assertEqual(parse_rows(app.options.write.call_args.args[0]),[old,ROW])
        self.assertEqual(app.config["sensor_bindings"],{S:ROW})
