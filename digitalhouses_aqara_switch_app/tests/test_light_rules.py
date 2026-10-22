"""Smart light options, service allowlists, and HA dispatch; no physical lights."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json

from aqara_switch.catalog import CatalogError
from aqara_switch.actions import ActionError, plan_action
from aqara_switch.control import HAClient, light_action
from aqara_switch.entity_options import _save_profiles, current, parse_rows

ID="switch.livingroomaqaraswitch"
COORD="0x00124b002e1330dd"
IEEE="0x00158d0000000001"
LIGHT="light.dh_aqara_lab_led_strip"
L2="light.dh_aqara_lab_spots"

def profiles():
    return {"rooms":[{"area_id":None,"name":"Без комнаты","switches":[{
        "coordinator_ieee":COORD,"base_topic":"zigbee2mqtt",
        "logical_name":"aqara_livingroom","ieee":IEEE,"entity_id":ID,
        "fingerprint":{"vendor":"Aqara","model":"ABC",
                       "actions":["single","double","hold","single_center"],
                       "setting_keys":[],"relay_channels":[]},
        "settings":{},"bindings":{},"panel_relay":None}]}]}

def yaml_for(rule):
    import yaml
    return yaml.safe_dump([{ID:{"enabled":True,"actions":{"single":rule}}}],
                           sort_keys=False)

class SmartLightTests(TestCase):
    def test_simple_list_preserved_in_yaml_and_toggle_plan(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"store.json"
            _save_profiles(path,profiles())
            options={"switches":yaml_for([LIGHT,L2])}
            self.assertEqual(parse_rows(options)[0]["actions"]["single"],[LIGHT,L2])
            sw=current(options,path)["rooms"][0]["switches"][0]
            self.assertEqual(light_action(sw,"single"),{
                "service":"light.toggle","target":{"entity_id":[LIGHT,L2]}})

    def test_brightness_kelvin_fade_and_rgb_single_service(self):
        cases=[
            ({"service":"light.turn_on","targets":[LIGHT,L2],
              "brightness_pct":75,"color_temp_kelvin":3000,"transition":2},
             {"brightness_pct":75,"color_temp_kelvin":3000,"transition":2}),
            ({"service":"light.turn_on","targets":[LIGHT],
              "brightness_pct":40,"rgb_color":[255,80,30]},
             {"brightness_pct":40,"rgb_color":[255,80,30]}),
            ({"service":"light.turn_on","targets":[LIGHT],
              "brightness_step_pct":-10},
             {"brightness_step_pct":-10}),
            ({"service":"light.turn_off","targets":[LIGHT],
              "transition":1.5},
             {"transition":1.5}),
            ({"service":"light.toggle","targets":[LIGHT],
              "brightness_pct":60,"rgb_color":[10,20,30]},
             {"brightness_pct":60,"rgb_color":[10,20,30]}),
        ]
        with TemporaryDirectory() as td:
            path=Path(td)/"store.json"
            _save_profiles(path,profiles())
            for rule,data in cases:
                with self.subTest(rule=rule):
                    sw=current({"switches":yaml_for(rule)},path)["rooms"][0]["switches"][0]
                    command=light_action(sw,"single")
                    self.assertEqual(command["service"],rule["service"])
                    self.assertEqual(command["target"]["entity_id"],rule["targets"])
                    self.assertEqual(command["data"],data)

    def test_bad_rules_fail_closed(self):
        base={"service":"light.turn_on","targets":[LIGHT]}
        invalid=[
            {**base,"brightness_pct":101}, {**base,"brightness_pct":True},
            {**base,"brightness_step_pct":0},
            {**base,"brightness_step_pct":101},
            {**base,"brightness_pct":50,"brightness_step_pct":10},
            {**base,"color_temp_kelvin":999},
            {**base,"color_temp_kelvin":3000,"rgb_color":[255,2,3]},
            {**base,"rgb_color":[256,0,0]},
            {**base,"rgb_color":[True,0,0]},
            {**base,"brightness_step_pct":5,"rgb_color":[1,2,3]},
            {**base,"transition":-1},{**base,"transition":61},
            {**base,"transition":False},
            {**base,"color_name":"red"}, {**base,"effect":"party"},
            {**base,"targets":["switch.actual_relay"]},
            {**base,"targets":[LIGHT,LIGHT]}, {**base,"targets":[]},
            {**base,"service":"homeassistant.restart"},
            {"service":"light.turn_off","targets":[LIGHT],"brightness_pct":50},
            {"service":"light.toggle","targets":[LIGHT],"brightness_step_pct":10},
            {"targets":[LIGHT],"brightness_pct":40},
        ]
        with TemporaryDirectory() as td:
            path=Path(td)/"store.json"
            _save_profiles(path,profiles())
            for rule in invalid:
                with self.subTest(rule=rule):
                    with self.assertRaises(CatalogError):
                        current({"switches":yaml_for(rule)},path)

    def test_only_supported_physical_action_dispatches(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"store.json"
            _save_profiles(path,profiles())
            sw=current({"switches":yaml_for({
                "service":"light.turn_on","targets":[LIGHT],
                "rgb_color":[2,3,4]})},path)["rooms"][0]["switches"][0]
            self.assertIsNone(light_action(sw,"unknown"))
            self.assertIsNone(light_action(sw,"hold"))
            self.assertEqual(light_action(sw,"single")["data"]["rgb_color"],[2,3,4])

    def test_one_allowlisted_ha_service_call_with_data_and_no_relay(self):
        requests=[]
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*a):pass
        def opener(request,timeout):
            requests.append((request.full_url,json.loads(request.data)))
            return Response()
        client=HAClient("dummy-token")
        with patch("urllib.request.urlopen",side_effect=opener):
            client.execute({"service":"light.turn_on",
                            "target":{"entity_id":[LIGHT,L2]},
                            "data":{"brightness_pct":70,"color_temp_kelvin":3300}})
            client.execute({"service":"light.turn_off",
                            "target":{"entity_id":[LIGHT]},"data":{"transition":1}})
        self.assertEqual(requests,[
            ("http://supervisor/core/api/services/light/turn_on",
             {"entity_id":[LIGHT,L2],"brightness_pct":70,"color_temp_kelvin":3300}),
            ("http://supervisor/core/api/services/light/turn_off",
             {"entity_id":[LIGHT],"transition":1}),
        ])
        with self.assertRaises(ValueError):
            client.execute({"service":"switch.toggle","target":{"entity_id":["switch.foo"]}})
        with self.assertRaises(ValueError):
            client.execute({"service":"light.turn_on","target":{"entity_id":[LIGHT]},
                            "data":{"color_temp_kelvin":2500,"rgb_color":[2,3,4]}})
        self.assertEqual(len(requests),2)


if __name__=="__main__":
    import unittest
    unittest.main()
