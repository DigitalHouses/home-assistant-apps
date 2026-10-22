"""Scan includes Aqara button devices under stable switch.* YAML config keys."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from aqara_switch.scan import scan_once
from aqara_switch.entity_options import parse_rows, current
from aqara_switch.ha_registry import areas_from_registries, switch_entities
from aqara_switch.catalog import CatalogError

COORD="0x00124b002e1330dd"
IEEE="0x00158d0000000001"
ENTITY="switch.livingroomaqaraswitch"
NAME="aqara_button"

def z2m_device(ieee=IEEE,model="WXKG13LM",name=NAME):
    return {"ieee_address":ieee,"friendly_name":name,"type":"EndDevice",
            "model_id":"lumi.remote.test",
            "definition":{"vendor":"Aqara","model":model,"exposes":[
                {"type":"enum","property":"action","access":1,"values":["single","double"]}]}}
def snap(ieee=IEEE,model="WXKG13LM",name=NAME):
    return {"base_topic":"zigbee2mqtt","coordinator_ieee":COORD,
            "devices":json.dumps([{"ieee_address":COORD,"type":"Coordinator"},
                                  z2m_device(ieee,model,name)]).encode(),"states":{}}

class Options:
    def __init__(self):
        self.options={"log_level":"info","switches":"[]"}
        self.writes=0
    def read(self): return dict(self.options)
    def write(self, value):
        self.options=dict(value)
        self.writes+=1

class Registry:
    def __init__(self, entities=None, ieee=IEEE):
        self.ieee=ieee
        self.entities=entities if entities is not None else [
            {"device_id":"ha-1","entity_id":ENTITY,"disabled_by":None}]
    def fetch(self):
        devices=[{"id":"ha-1","area_id":"living","identifiers":[
            ["mqtt","zigbee2mqtt_"+self.ieee]],"connections":[]}]
        areas=[{"area_id":"living","name":"Гостиная"}]
        return devices,areas,self.entities

class ScanTests(unittest.TestCase):
    def test_scan_uses_real_entity_and_repeat_no_duplicates(self):
        with TemporaryDirectory() as td, patch("aqara_switch.scan.STORE_PATH",Path(td)/"store.json"):
            opts=Options()
            data,report=scan_once([snap()],opts,Registry())
            self.assertEqual(report["added"][0]["name"],NAME)
            self.assertEqual(opts.writes,1)
            self.assertEqual(parse_rows(opts.read()),[{"entity_id":ENTITY,"enabled":True,"actions":{}}])
            self.assertEqual(data["rooms"][0]["switches"][0]["entity_id"],ENTITY)
            new,report=scan_once([snap()],opts,Registry())
            self.assertEqual(report["added"],[])
            self.assertEqual(opts.writes,1)
            self.assertEqual(new,data)

    def test_battery_button_with_only_ha_event_gets_logical_key(self):
        with TemporaryDirectory() as td, patch("aqara_switch.scan.STORE_PATH", Path(td)/"store.json"):
            opts = Options()
            dev, report = scan_once([snap()], opts, Registry(entities=[
                {"device_id": "ha-1", "entity_id": "event.aqara_button_action"}]))
            key = "switch.aqara_button"
            self.assertEqual(opts.writes, 1)
            self.assertEqual(report["added"][0]["name"], NAME)
            self.assertEqual(parse_rows(opts.read()), [
                {"entity_id": key, "enabled": True, "actions": {}}])
            self.assertEqual(report["logical_only"], [{"name": NAME, "key": key}])
            self.assertEqual(dev["rooms"][0]["switches"][0]["entity_source"], "logical")
            again, report = scan_once([snap()], opts, Registry(entities=[
                {"device_id": "ha-1", "entity_id": "event.aqara_button_action"}]))
            self.assertEqual(report["added"], [])
            self.assertEqual(opts.writes, 1)
            self.assertEqual(again, dev)

    def test_multiple_switch_entities_use_logical_key_not_random_relay(self):
        with TemporaryDirectory() as td, patch("aqara_switch.scan.STORE_PATH",Path(td)/"store.json"):
            opts=Options()
            data, report=scan_once([snap()],opts,Registry(entities=[
                {"device_id":"ha-1","entity_id":"switch.a"},
                {"device_id":"ha-1","entity_id":"switch.b"}]))
            self.assertEqual(opts.writes, 1)
            self.assertEqual(data["rooms"][0]["switches"][0]["entity_id"], "switch.aqara_button")
            self.assertEqual(report["logical_only"][0]["key"], "switch.aqara_button")

    def test_no_ha_device_is_not_reason_to_omit_zigbee_button(self):
        class EmptyRegistry:
            def fetch(self):
                return [], [], []
        with TemporaryDirectory() as td, patch("aqara_switch.scan.STORE_PATH",Path(td)/"store.json"):
            opts=Options()
            data, report=scan_once([snap()],opts,EmptyRegistry())
            self.assertEqual(opts.writes,1)
            self.assertEqual(data["rooms"][0]["name"],"Без комнаты")
            self.assertEqual(data["rooms"][0]["switches"][0]["entity_id"],"switch.aqara_button")

    def test_same_key_survives_ha_entity_arrival(self):
        with TemporaryDirectory() as td, patch("aqara_switch.scan.STORE_PATH",Path(td)/"store.json"):
            opts=Options()
            scan_once([snap()],opts,Registry(entities=[]))
            before=opts.read()["switches"]
            data, report=scan_once([snap()],opts,Registry())
            self.assertEqual(opts.read()["switches"],before)
            self.assertEqual(data["rooms"][0]["switches"][0]["entity_id"],"switch.aqara_button")
            self.assertEqual(opts.writes,1)

    def test_renamed_devices_dont_reuse_same_ieee_key_without_confirmation(self):
        with TemporaryDirectory() as td, patch("aqara_switch.scan.STORE_PATH",Path(td)/"store.json"):
            opts=Options()
            scan_once([snap()],opts,Registry(entities=[]))
            _, report=scan_once([snap(name="new_aqara_button")],opts,Registry(entities=[]))
            self.assertEqual(report["added"],[])
            self.assertIn("known_ieee_renamed",str(report["problems"]))
            self.assertEqual(opts.writes,1)

    def test_area_matching_is_strict(self):
        dev=[{"id":"ha-1","area_id":"living","identifiers":[["mqtt","zigbee2mqtt_"+IEEE]]}]
        self.assertEqual(areas_from_registries(dev,[{"area_id":"living","name":"Гостиная"}],{IEEE})[IEEE]["name"],"Гостиная")
        with self.assertRaisesRegex(CatalogError,"Ambiguous"):
            areas_from_registries(dev+dev,[{"area_id":"living","name":"Гостиная"}],{IEEE})

    def test_compatible_button_replacement_keeps_logical_key_and_two_lights(self):
        new_ieee="0x00158d0000000002"
        with TemporaryDirectory() as td, patch("aqara_switch.scan.STORE_PATH", Path(td)/"store.json"):
            opts=Options()
            scan_once([snap()],opts,Registry(entities=[]))
            opts.options["switches"] = """
- switch.aqara_button:
    enabled: true
    actions:
      single:
        - light.dh_aqara_lab_chandelier
        - light.dh_aqara_lab_spots
"""
            merged,report=scan_once([snap(ieee=new_ieee)],opts,
                                    Registry(entities=[],ieee=new_ieee))
            self.assertEqual(report["replaced"],["switch.aqara_button"])
            item=merged["rooms"][0]["switches"][0]
            self.assertEqual(item["ieee"],new_ieee)
            self.assertEqual(item["bindings"]["single"]["targets"],
                             ["light.dh_aqara_lab_chandelier","light.dh_aqara_lab_spots"])

    def test_manual_rescan_reintroduces_deleted_yaml_row(self):
        with TemporaryDirectory() as td, patch("aqara_switch.scan.STORE_PATH",Path(td)/"store.json"):
            opts=Options()
            scan_once([snap()],opts,Registry(entities=[]))
            opts.options["switches"]="[]"
            data,report=scan_once([snap()],opts,Registry(entities=[]))
            self.assertEqual(report["added"],[])
            self.assertEqual(opts.writes,2)
            self.assertEqual(parse_rows(opts.read())[0]["entity_id"],"switch.aqara_button")
            self.assertEqual(data["rooms"][0]["switches"][0]["entity_id"],"switch.aqara_button")

    def test_slug_collision_has_stable_network_key(self):
        from aqara_switch.scan import _choose_key
        known={}
        first={"coordinator_ieee":COORD,"logical_name":"button-1","base_topic":"zigbee2mqtt_1"}
        second={"coordinator_ieee":COORD,"logical_name":"button_1","base_topic":"zigbee2mqtt_1"}
        key1,source1=_choose_key(first,known,{},None)
        key2,source2=_choose_key(second,known,
                               {key1:(COORD,"button-1")},None)
        self.assertEqual(key1,"switch.button_1")
        self.assertEqual(key2,"switch.zigbee2mqtt_1_button_1")
        self.assertEqual(source1,source2)

    def test_compatible_replacement_preserves_actions(self):
        new_ieee="0x00158d0000000002"
        with TemporaryDirectory() as td, patch("aqara_switch.scan.STORE_PATH",Path(td)/"store.json"):
            opts=Options()
            scan_once([snap()],opts,Registry())
            opts.options["switches"] = """
- switch.livingroomaqaraswitch:
    enabled: true
    actions:
      single:
        - light.dh_aqara_lab_chandelier
        - light.dh_aqara_lab_spots
"""
            merged,report=scan_once([snap(ieee=new_ieee)],opts,Registry(ieee=new_ieee))
            self.assertEqual(report["replaced"],[ENTITY])
            self.assertEqual(merged["rooms"][0]["switches"][0]["ieee"],new_ieee)
            self.assertEqual(merged["rooms"][0]["switches"][0]["bindings"]["single"]["targets"],
                             ["light.dh_aqara_lab_chandelier","light.dh_aqara_lab_spots"])


if __name__=="__main__":
    unittest.main()
