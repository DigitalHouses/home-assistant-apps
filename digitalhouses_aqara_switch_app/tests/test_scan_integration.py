"""Unit acceptance for the manual-only scan and HA Area correlation."""
from __future__ import annotations
import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs/app"))
try:
    from aqara_switch.catalog import CatalogError
    from aqara_switch.configuration import parse_configuration, encode_configuration
    from aqara_switch.ha_registry import areas_from_registries
    from aqara_switch.scan import scan_once
    from aqara_switch.runtime import verified_snapshots, bridge_path
    from aqara_switch.mqtt_ui import configuration, SCAN_REQUEST, wire_payload
finally:
    sys.path.pop(0)

COORD="0x00124b002e1330dd"
IEEE="0x00158d0000000001"


def z2m_device(*, named="aqara_button", vendor="Aqara", wired=False):
    exposes = [{"type":"enum","name":"action","property":"action","access":1,
                "values":["single","double"]}]
    if wired:
        exposes += [
            {"type":"enum","name":"operation_mode","property":"operation_mode",
             "access":3,"values":["control_relay","decoupled"]},
            {"type":"switch","features":[{"type":"binary","property":"state_left","access":7}]},
        ]
    return {
        "ieee_address":IEEE,"friendly_name":named,"type":"Router" if wired else "EndDevice",
        "model_id":"lumi.remote.test",
        "definition":{"vendor":vendor,"model":"WXKG17LM","exposes":exposes},
    }


def snapshot(*, wired=False, states=None):
    devices=[{"ieee_address":COORD,"type":"Coordinator"},z2m_device(wired=wired)]
    return {"base_topic":"zigbee2mqtt","coordinator_ieee":COORD,
            "devices":json.dumps(devices).encode(),"states":states or {}}


class FakeOptions:
    def __init__(self):
        self.options={"configuration_yaml":"rooms: []\n","log_level":"info"}
        self.writes=0
    def read(self):
        return dict(self.options)
    def write(self, value):
        self.writes+=1
        self.options=dict(value)


class FakeRegistry:
    def __init__(self, areas=True):
        self.areas=areas
    def fetch(self):
        if not self.areas:
            return [],[]
        return ([{"id":"ha-device-1","area_id":"living_room",
                  "identifiers":[["mqtt","zigbee2mqtt_"+IEEE]],
                  "connections":[]}],
                [{"area_id":"living_room","name":"Гостиная"}])


class ScanIntegrationTest(unittest.TestCase):
    def test_manual_scan_imports_once(self):
        options=FakeOptions()
        config, report=scan_once([snapshot()],options,FakeRegistry())
        self.assertEqual(options.writes,1)
        self.assertEqual(report["scanned"],1)
        self.assertEqual(report["added"][0]["name"],"aqara_button")
        self.assertEqual(config["rooms"][0]["name"],"Гостиная")
        self.assertEqual(config["rooms"][0]["switches"][0]["settings"],{})
        current=parse_configuration(options.read())
        current["rooms"][0]["switches"][0]["bindings"]={
            "single":{"action":"toggle","targets":["light.dh_aqara_lab_chandelier"]}
        }
        options.options["configuration_yaml"]=encode_configuration(current)
        again, report=scan_once([snapshot()],options,FakeRegistry(areas=False))
        self.assertEqual(options.writes,1)
        self.assertEqual(report["added"],[])
        self.assertEqual(report["skipped"],["aqara_button"])
        self.assertEqual(again,current)

    def test_wired_without_confirmed_mqtt_settings_does_not_import(self):
        options=FakeOptions()
        result,report=scan_once([snapshot(wired=True)],options,FakeRegistry())
        self.assertEqual(options.writes,0)
        self.assertEqual(result["rooms"],[])
        self.assertEqual(report["scanned"],0)
        self.assertIn("not confirmed",report["problems"][0]["reason"])

    def test_wired_confirmed_is_imported(self):
        options=FakeOptions()
        result,report=scan_once([snapshot(wired=True,states={
            "aqara_button":{"operation_mode":"decoupled"}
        })],options,FakeRegistry())
        self.assertEqual(result["rooms"][0]["switches"][0]["settings"],
                         {"operation_mode":"decoupled"})
        self.assertEqual(len(report["added"]),1)

    def test_ha_registry_ambiguous_identity_is_error(self):
        device={"area_id":"living_room","identifiers":[["mqtt","zigbee2mqtt_"+IEEE]]}
        with self.assertRaisesRegex(CatalogError,"Ambiguous"):
            areas_from_registries([device,dict(device)],
                                  [{"area_id":"living_room","name":"Гостиная"}],{IEEE})

    def test_ha_registry_never_matches_friendly_name(self):
        obj={"area_id":"living_room","identifiers":[["mqtt","aqara_button"]],"connections":[]}
        index=areas_from_registries([obj],
                    [{"area_id":"living_room","name":"Гостиная"}],{IEEE})
        self.assertIsNone(index[IEEE])

    def test_area_is_absent_when_unassigned(self):
        index=areas_from_registries([],[],{IEEE})
        self.assertIsNone(index[IEEE])

    def test_supervisor_yaml_rejects_invalid_shapes(self):
        with self.assertRaises(CatalogError):
            parse_configuration({"configuration_yaml":"rooms:\n  - foo\n"})

    def test_mqtt_discovery_has_scan_button_and_no_relay_writes(self):
        config=configuration("0.1.1")
        self.assertEqual(config["components"]["scan"]["command_topic"],SCAN_REQUEST)
        self.assertIn("devices_details",config["components"])
        self.assertIn("scan_state",config["components"])
        self.assertNotIn("tojson",wire_payload("0.1.1"))
        self.assertEqual(config["components"]["card"]["default_entity_id"],
                         "sensor.dh_aqara_switch_app_card")

    def test_snapshot_requires_both_coordinator_sources(self):
        state=snapshot()
        nets={"zigbee2mqtt":{
            "info":json.dumps({"coordinator":{"ieee_address":COORD}}).encode(),
            "devices":state["devices"],"states":{}
        }}
        self.assertEqual(len(verified_snapshots(nets)),1)
        broken=dict(nets["zigbee2mqtt"])
        broken["info"]=json.dumps({"coordinator":{
            "ieee_address":"0x00124b002e1330de"}}).encode()
        self.assertEqual(verified_snapshots({"zigbee2mqtt":broken}),[])

    def test_untrusted_topics_are_ignored(self):
        self.assertIsNone(bridge_path("homeassistant/bridge/info"))
        self.assertIsNone(bridge_path("zigbee2mqtt/bridge/request/device/remove"))
        self.assertEqual(bridge_path("zigbee2mqtt/bridge/devices"),
                         ("zigbee2mqtt","devices"))


if __name__=="__main__":
    unittest.main()
