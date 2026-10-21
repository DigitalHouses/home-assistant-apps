"""Explicit Scan must reuse real HA entity registry, never invent switch.*."""
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

    def test_no_switch_entity_reports_problem_and_does_not_write(self):
        with TemporaryDirectory() as td, patch("aqara_switch.scan.STORE_PATH",Path(td)/"store.json"):
            opts=Options()
            data, report=scan_once([snap()],opts,Registry(entities=[
                {"device_id":"ha-1","entity_id":"event.aqara_button_action"}]))
            self.assertEqual(opts.writes,0)
            self.assertEqual(data["rooms"],[])
            self.assertIn("No existing switch.* entity",str(report["problems"]))

    def test_multiple_switch_entities_are_not_guessed(self):
        with TemporaryDirectory() as td, patch("aqara_switch.scan.STORE_PATH",Path(td)/"store.json"):
            opts=Options()
            data, report=scan_once([snap()],opts,Registry(entities=[
                {"device_id":"ha-1","entity_id":"switch.a"},
                {"device_id":"ha-1","entity_id":"switch.b"}]))
            self.assertEqual(opts.writes,0)
            self.assertEqual(data["rooms"],[])
            self.assertIn("Multiple switch.*",str(report["problems"]))

    def test_area_matching_is_strict(self):
        dev=[{"id":"ha-1","area_id":"living","identifiers":[["mqtt","zigbee2mqtt_"+IEEE]]}]
        self.assertEqual(areas_from_registries(dev,[{"area_id":"living","name":"Гостиная"}],{IEEE})[IEEE]["name"],"Гостиная")
        with self.assertRaisesRegex(CatalogError,"Ambiguous"):
            areas_from_registries(dev+dev,[{"area_id":"living","name":"Гостиная"}],{IEEE})

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
