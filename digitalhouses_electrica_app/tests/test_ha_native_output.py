"""v0.1.15: HA-native light fallback must not bypass Zigbee2MQTT verification."""
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import Mock, patch

from aqara_switch.control import HAClient
from aqara_switch.lab_lights import authorized_ha_light_ids, partition_commands
from aqara_switch.runtime import Application
from test_lab_rest_fallback import (
    PROFILE, DEVICE, BASE, COORD, NAME, LAB, PHYSICAL, PHYSICAL_DEVICE,
    PHYSICAL_ROUTE, FakeMQTT, packet)

TV = "light.tv_switch"


class SafePlatformTests(unittest.TestCase):
    def test_requires_positive_unique_non_mqtt_platform(self):
        requested={TV,"light.mqtt_light","light.disabled","light.unknown","light.duplicate"}
        entities=[
            {"entity_id":TV,"platform":"template","disabled_by":None},
            {"entity_id":"light.mqtt_light","platform":"mqtt","disabled_by":None},
            {"entity_id":"light.disabled","platform":"template","disabled_by":"user"},
            {"entity_id":"light.unknown","disabled_by":None},
            {"entity_id":"light.duplicate","platform":"template"},
            {"entity_id":"light.duplicate","platform":"template"},
        ]
        self.assertEqual(authorized_ha_light_ids(entities,requested),{TV})
        self.assertEqual(authorized_ha_light_ids(None,requested),set())
        self.assertEqual(authorized_ha_light_ids([{"entity_id":TV}],{TV}),set())
        self.assertEqual(authorized_ha_light_ids([{"entity_id":TV,"platform":"mqtt"}],{TV}),set())

    def test_z2m_route_wins_even_if_registry_says_template(self):
        command={"service":"light.toggle","target":{"entity_id":[TV]}}
        z2m,ha=partition_commands([command],{TV:{"base_topic":BASE}},{TV})
        self.assertEqual(len(z2m),1)
        self.assertEqual(ha,[])

    def test_ha_rest_reads_valid_native_target_and_rejects_invalid_id(self):
        calls=[]
        class Response:
            status=200
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def read(self): return b'{"state":"off"}'
        def urlopen(request,timeout):
            calls.append((request.full_url,request.get_method()))
            return Response()
        with patch("urllib.request.urlopen",side_effect=urlopen):
            state=HAClient("t").read_light_state(TV)
        self.assertEqual(state,"off")
        self.assertEqual(calls,[("http://supervisor/core/api/states/"+TV,"GET")])
        for invalid in ("switch.tv_switch","light./x","light.foo/bar"):
            with self.assertRaises(ValueError):
                HAClient("t").read_light_state(invalid)


class NativeLightIntegration(unittest.TestCase):
    def build(self, targets, *, tv="off", physical="ON", avail="online",
              registry=None, route=False, lab="on"):
        profiles=deepcopy(PROFILE)
        profiles["light_routes"]={PHYSICAL:deepcopy(PHYSICAL_ROUTE)} if route else {}
        yaml_text='''- switch.aqara_battery_button:
    enabled: true
    actions:
      double:
'''
        yaml_text+=''.join('        - '+entity+'\n' for entity in targets)
        options=Mock()
        options.read.return_value={"switches":yaml_text}
        ha=Mock()
        ha.read_light_state.return_value=tv
        ha.read_lab_state.return_value=lab
        ha.execute.return_value=None
        source=Mock()
        source.fetch_entities.return_value=(
            [{"entity_id":TV,"platform":"template","disabled_by":None}]
            if registry is None else registry)
        with TemporaryDirectory() as td,patch(
            "aqara_switch.entity_options._read_profiles",return_value=profiles):
            app=Application(FakeMQTT,options=options,registry=source,
                last_scan_path=Path(td)/"scan.json",version="0.1.15",
                ha_client=ha)
        app._on_connect(None,None,None,0)
        app._on_message(None,None,packet(BASE+"/bridge/info",
            {"coordinator":{"ieee_address":COORD}},True))
        app._on_message(None,None,packet(BASE+"/bridge/devices",
            [{"type":"Coordinator","ieee_address":COORD},DEVICE,PHYSICAL_DEVICE],True))
        app._on_message(None,None,packet(BASE+"/bridge/state",
            {"state":"online"},True))
        if route:
            app._on_message(None,None,types.SimpleNamespace(
                topic=BASE+"/led_strip/availability",payload=avail.encode(),
                retain=True,dup=False))
        app._on_message(None,None,packet(BASE+"/led_strip",{"state":physical}))
        return app,ha,source

    def run_button(self,app,count=1):
        result=[]
        app._on_message(None,None,packet(BASE+"/"+NAME,{"action":"double"}))
        self.assertEqual(app._jobs.qsize(),1)
        if count==2:
            job=app._jobs.queue[0]
            app._jobs.put_nowait(job)
        def collect(**kw):
            result.append(kw)
            if len(result)>=count:app._stop.set()
        app._publish_action=collect
        app._run_actions()
        mqtt=[(topic,json.loads(body)) for topic,body,retained
              in app.client.published if topic.endswith("/set")]
        return result,mqtt

    def test_tv_template_light_works_without_scan(self):
        app,ha,source=self.build([TV],tv="off")
        results,physical=self.run_button(app)
        self.assertEqual(physical,[])
        self.assertEqual(results[0]["state"],"sent")
        self.assertEqual(results[0]["target"],TV)
        ha.read_light_state.assert_called_once_with(TV)
        ha.execute.assert_called_once_with({
            "service":"light.turn_on","target":{"entity_id":[TV]},"data":{}})
        source.fetch_entities.assert_called_once()
        source.fetch.assert_not_called()

    def test_all_on_native_toggle_turns_tv_off(self):
        app,ha,_=self.build([TV],tv="on")
        results,_=self.run_button(app)
        self.assertEqual(results[0]["state"],"sent")
        self.assertEqual(ha.execute.call_args.args[0]["service"],"light.turn_off")

    def test_mixed_native_virtual_physical_single_decision(self):
        app,ha,source=self.build([TV,LAB,PHYSICAL],tv="off",
                                  lab="on",physical="ON",route=True)
        actions,mqtt=self.run_button(app)
        self.assertEqual(mqtt,[(BASE+"/led_strip/set",{"state":"ON"})])
        self.assertEqual(actions[0]["state"],"sent")
        self.assertEqual(actions[0]["error"],None)
        ha.read_light_state.assert_called_once_with(TV)
        ha.read_lab_state.assert_called_once_with(LAB)
        call=ha.execute.call_args.args[0]
        self.assertEqual(call["service"],"light.turn_on")
        self.assertCountEqual(call["target"]["entity_id"],[TV,LAB])
        source.fetch_entities.assert_called_once()

    def test_unmapped_mqtt_physical_still_skipped_not_ha(self):
        r=[{"entity_id":TV,"platform":"template"},
           {"entity_id":PHYSICAL,"platform":"mqtt"}]
        app,ha,_=self.build([TV,PHYSICAL],tv="off",registry=r,route=False)
        actions,mqtt=self.run_button(app)
        self.assertFalse(mqtt)
        self.assertEqual(actions[0]["state"],"partial")
        self.assertIn("No verified Z2M route",actions[0]["error"])
        self.assertEqual(ha.read_light_state.call_args_list[0].args,(TV,))
        self.assertEqual(ha.read_light_state.call_count,1)

    def test_offline_z2m_physical_remains_skipped_even_with_ha_available(self):
        r=[{"entity_id":TV,"platform":"template"},
           {"entity_id":PHYSICAL,"platform":"template"}]  # contradictory registry
        app,ha,_=self.build([TV,PHYSICAL],tv="off",registry=r,route=True,avail="offline")
        actions,mqtt=self.run_button(app)
        self.assertEqual(mqtt,[])
        self.assertEqual(actions[0]["state"],"partial")
        self.assertIn("offline",actions[0]["error"])
        ha.read_light_state.assert_called_once_with(TV)

    def test_unknown_or_mqtt_only_light_is_not_ha_fallback(self):
        for registry in ([],[{"entity_id":TV,"platform":"mqtt"}],
                         [{"entity_id":TV,"platform":"template","disabled_by":"user"}]):
            with self.subTest(registry=registry):
                app,ha,_=self.build([TV],registry=registry)
                actions,mqtt=self.run_button(app)
                self.assertEqual(mqtt,[])
                self.assertEqual(actions[0]["state"],"skipped")
                self.assertIn("No verified Z2M route",actions[0]["error"])
                ha.execute.assert_not_called()
                ha.read_light_state.assert_not_called()

    def test_ha_state_unavailable_must_not_toggle(self):
        app,ha,_=self.build([TV],tv="unavailable")
        actions,mqtt=self.run_button(app)
        self.assertEqual(mqtt,[])
        self.assertEqual(actions[0]["state"],"skipped")
        ha.execute.assert_not_called()

    def test_registry_failure_keeps_native_light_off(self):
        app,ha,source=self.build([TV])
        source.fetch_entities.side_effect=ConnectionError("registry offline")
        actions,mqtt=self.run_button(app)
        self.assertEqual(mqtt,[])
        self.assertEqual(actions[0]["state"],"skipped")
        ha.execute.assert_not_called()

    def test_rapid_double_press_uses_ha_shadow_and_cached_registry(self):
        app,ha,source=self.build([TV],tv="off")
        results,mqtt=self.run_button(app,count=2)
        self.assertEqual(mqtt,[])
        self.assertEqual([c.args[0]["service"] for c in
                          ha.execute.call_args_list],
                         ["light.turn_on","light.turn_off"])
        self.assertEqual([a["state"] for a in results],["sent","sent"])
        source.fetch_entities.assert_called_once()


if __name__=="__main__":
    unittest.main()

class NativeRegistryWebsocketTests(unittest.TestCase):
    def test_fetch_entities_only_uses_read_only_registry_method(self):
        import sys
        from aqara_switch.ha_registry import HARegistryClient
        class Socket:
            def __init__(self):
                self.frames=iter([
                    {"type":"auth_required"}, {"type":"auth_ok"},
                    {"id":1,"type":"result","success":True,
                     "result":[{"entity_id":TV,"platform":"template"}]}])
                self.sent=[]
                self.closed=False
            def recv(self):return json.dumps(next(self.frames))
            def send(self,frame):self.sent.append(json.loads(frame))
            def close(self):self.closed=True
        sock=Socket()
        fake=types.SimpleNamespace(create_connection=lambda *a,**kw:sock)
        with patch.dict(sys.modules,{"websocket":fake}):
            rows=HARegistryClient("token").fetch_entities()
        self.assertEqual(rows,[{"entity_id":TV,"platform":"template"}])
        self.assertEqual(sock.sent,[
            {"type":"auth","access_token":"token"},
            {"id":1,"type":"config/entity_registry/list"}])
        self.assertTrue(sock.closed)
