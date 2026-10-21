"""Passive group monitoring and MQTT optimistic semantics."""
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

from aqara_switch.light_observer import GroupObserver, selection
from aqara_switch.runtime import Application
from aqara_switch.mqtt_ui import ROOT

GROUPS = json.dumps([{"friendly_name":"zg_bedroom_tube_lights","id":112,"members":[
    {"ieee_address":"0xa4c13801e9d05b42","endpoint":1},
    {"ieee_address":"0xa4c138b9364cf476","endpoint":1}]}]).encode()
DEVICES = json.dumps([
    {"ieee_address":"0xa4c13801e9d05b42","friendly_name":"1f_bedroom_tubelight_L"},
    {"ieee_address":"0xa4c138b9364cf476","friendly_name":"1f_bedroom_tubelight_R"},
]).encode()

class FakeMQTT:
    class Client:
        def __init__(self, **kwargs):
            self.subscriptions, self.published = [], []
        def will_set(self, *a, **k): pass
        def reconnect_delay_set(self, *a, **k): pass
        def subscribe(self, topic, qos=1):
            self.subscriptions.append(topic)
            return (0, 1)
        def publish(self, topic, data, qos=1, retain=False):
            self.published.append((topic, data))
            return types.SimpleNamespace(rc=0)

class PassiveObserverTests(unittest.TestCase):
    def test_opt_in_validation(self):
        self.assertIsNone(selection({"rooms":[]}))
        self.assertEqual(selection({"light_monitor":{"base_topic":"zigbee2mqtt_1",
                     "group":"zg_bedroom_tube_lights"}}),
                         ("zigbee2mqtt_1","zg_bedroom_tube_lights"))
        with self.assertRaises(ValueError):
            selection({"light_monitor":{"base_topic":"zigbee2mqtt_1","group":"a/#"}})

    def test_members_report_unverified(self):
        with tempfile.TemporaryDirectory() as td:
            obs = GroupObserver(("zigbee2mqtt_1","zg_bedroom_tube_lights"),
                                Path(td)/"events.jsonl")
            topics = obs.inventory(GROUPS, DEVICES)
            self.assertIn("zigbee2mqtt_1/1f_bedroom_tubelight_L", topics)
            self.assertEqual(obs.snapshot()["member_count"], 2)
            self.assertEqual(obs.snapshot()["confirmed_count"], 0)
            self.assertEqual(obs.snapshot()["members"][0]["state"], "unknown")
            obs.accept("zigbee2mqtt_1/1f_bedroom_tubelight_L",
                       b'{"state":"OFF","brightness":254}', True)
            obs.accept("zigbee2mqtt_1/zg_bedroom_tube_lights",
                       b'{"state":"ON"}', False)
            snap = obs.snapshot()
            self.assertEqual(snap["observed_count"], 1)
            self.assertEqual(snap["confirmed_count"], 0)
            self.assertEqual(snap["members"][0]["confidence"], "unverified")
            self.assertEqual(snap["members"][1]["confidence"], "unknown")
            self.assertEqual(snap["group_state"], "ON")
            self.assertEqual(len((Path(td)/"events.jsonl").read_text().splitlines()), 2)
            obs.reset_connection()
            self.assertEqual(obs.snapshot()["member_count"], 0)

    def test_missing_member_unknown(self):
        obs = GroupObserver(("zigbee2mqtt_1","wanted"))
        self.assertEqual(obs.inventory(b"[]",DEVICES),[])
        self.assertEqual(obs.snapshot()["state"],"group_missing")
        group = json.dumps([{"friendly_name":"wanted","id":12,
                             "members":[{"ieee_address":"0x0000000000000001","endpoint":1}]}]).encode()
        self.assertEqual(obs.inventory(group,DEVICES),["zigbee2mqtt_1/wanted"])
        self.assertEqual(obs.snapshot()["members"][0]["confidence"],"unknown")

    def test_runtime_subscribe_and_never_control(self):
        with tempfile.TemporaryDirectory() as td:
            opts = Mock()
            opts.read.return_value = {"configuration_yaml":
                "rooms: []\nlight_monitor:\n  base_topic: zigbee2mqtt_1\n  group: zg_bedroom_tube_lights\n"}
            app = Application(FakeMQTT,options=opts,registry=Mock(),
                              last_scan_path=Path(td)/"scan.json",version="0.1.2")
            app.observer.logfile = Path(td)/"events.jsonl"
            app._on_connect(None,None,None,0)
            def msg(topic,payload,retained=False):
                app._on_message(None,None,types.SimpleNamespace(
                    topic=topic,payload=payload,retain=retained))
            msg("zigbee2mqtt_1/bridge/groups",GROUPS,True)
            msg("zigbee2mqtt_1/bridge/devices",DEVICES,True)
            self.assertIn("zigbee2mqtt_1/1f_bedroom_tubelight_R",
                          app.client.subscriptions)
            msg("zigbee2mqtt_1/1f_bedroom_tubelight_L",b'{"state":"OFF"}')
            d = [json.loads(value) for topic,value in app.client.published
                 if topic == ROOT+"/light_group"][-1]
            self.assertEqual(d["state"],"observing")
            self.assertEqual(d["observed_count"],1)
            self.assertEqual(d["confirmed_count"],0)
            self.assertTrue(all(not topic.endswith(("/get","/set"))
                                for topic,_ in app.client.published))
            self.assertEqual(opts.write.call_count,0)

if __name__ == "__main__":
    unittest.main()
