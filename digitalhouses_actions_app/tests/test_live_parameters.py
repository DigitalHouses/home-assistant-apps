"""One persisted live flag, shared by HA and Ingress, no implicit adaptation."""
import tempfile
import types
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from actions.binding_store import BindingStore
from actions.catalog import CatalogError
from actions.mode_keeper import global_policy
from actions.mqtt_ui import AUTO_DAY_NIGHT_STATE,AUTO_DAY_NIGHT_COMMAND,configuration
from actions.runtime import Application
from test_runtime_manual_only import FakeClient

class LiveParametersTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.path=Path(td.name)
        self.settings={"auto_day_night":False,"maintenance_mode":False,
                       "auto_scan_interval":23,"restore_delay":0.7,"log_level":"info"}
        self.supervisor=Mock()
        self.supervisor.read.side_effect=lambda:deepcopy(self.settings)
        def save(settings):
            self.settings=deepcopy(settings)
        self.supervisor.write.side_effect=save
        self.store=BindingStore(self.supervisor,self.path/"bindings.json")
        self.app=self.build()
        self.app._on_connect(None,None,None,0)

    def build(self):
        return Application(types.SimpleNamespace(Client=FakeClient),options=self.store,
                           registry=Mock(),last_scan_path=self.path/"scan.json",version="0.3.8")

    def state(self):
        return [r for r in self.app.client.published_qos if r[0]==AUTO_DAY_NIGHT_STATE][-1]

    def packet(self,value,retain=False,dup=False):
        return types.SimpleNamespace(topic=AUTO_DAY_NIGHT_COMMAND,payload=value,retain=retain,dup=dup)

    def run_job(self):
        actual=self.app.set_auto_day_night
        def execute(value):
            try:return actual(value)
            finally:self.app._stop.set()
        with patch.object(self.app,"set_auto_day_night",side_effect=execute):
            self.app._run_actions()
        self.app._stop.clear()
        self.assertEqual(self.app._jobs.unfinished_tasks,0)

    def test_discovery_and_retained_state(self):
        switch=configuration("0.3.8")["components"]["auto_day_night"]
        self.assertEqual(switch["default_entity_id"],"switch.dh_actions_app_auto_day_night")
        self.assertEqual(switch["command_topic"],AUTO_DAY_NIGHT_COMMAND)
        self.assertEqual(switch["state_topic"],AUTO_DAY_NIGHT_STATE)
        self.assertFalse(switch["optimistic"])
        self.assertFalse(switch["retain"])
        self.assertIn(AUTO_DAY_NIGHT_COMMAND,self.app.client.subscriptions)
        self.assertEqual(self.state(),(AUTO_DAY_NIGHT_STATE,"OFF",1,True))
        self.supervisor.write.assert_not_called()

    def test_ingress_live_change_preserves_options_and_bindings_restart(self):
        original=deepcopy(self.settings)
        bindings=self.store.path.read_bytes()
        self.assertEqual(self.app.set_auto_day_night(True),{"auto_day_night":True})
        self.assertEqual(self.settings,{**original,"auto_day_night":True})
        self.assertEqual(self.store.path.read_bytes(),bindings)
        self.assertTrue(self.app.globals["auto_day_night"])
        self.assertTrue(self.app._jobs.empty())
        self.assertEqual(self.state(),(AUTO_DAY_NIGHT_STATE,"ON",1,True))
        self.assertTrue(self.build().globals["auto_day_night"])
        self.app.set_auto_day_night(True)
        self.supervisor.write.assert_called_once()
        self.app._on_connect(None,None,None,0)
        self.assertEqual(self.state(),(AUTO_DAY_NIGHT_STATE,"ON",1,True))

    def test_mqtt_only_valid_nonretained_command_and_worker(self):
        for packet in (self.packet(b"ON",retain=True),self.packet(b"ON",dup=True),
                       self.packet(b"1"),self.packet(b"on"),self.packet(b"toggle")):
            self.app._on_message(None,None,packet)
        self.assertTrue(self.app._jobs.empty())
        self.supervisor.write.assert_not_called()
        self.app._on_message(None,None,self.packet(b"ON"))
        self.run_job()
        self.assertTrue(self.settings["auto_day_night"])
        self.assertTrue(self.app.globals["auto_day_night"])
        self.assertEqual(self.state(),(AUTO_DAY_NIGHT_STATE,"ON",1,True))
        self.app._on_message(None,None,self.packet(b"OFF"))
        self.run_job()
        self.assertFalse(self.settings["auto_day_night"])
        self.assertFalse(self.app.globals["auto_day_night"])
        self.assertEqual(self.state(),(AUTO_DAY_NIGHT_STATE,"OFF",1,True))

    def test_persistence_failure_keeps_actual_state(self):
        self.supervisor.write.side_effect=OSError("Supervisor unavailable")
        with self.assertRaises(OSError):self.app.set_auto_day_night(True)
        self.assertFalse(self.app.globals["auto_day_night"])
        self.app._on_message(None,None,self.packet(b"ON"))
        with self.assertLogs("actions.runtime",level="ERROR"):self.run_job()
        self.assertEqual(self.state(),(AUTO_DAY_NIGHT_STATE,"OFF",1,True))
        with self.assertRaises(CatalogError):self.app.set_auto_day_night(1)

    def test_no_replay_and_stale_transition_invalidated(self):
        self.app._accept_home_profile({"mode":"day","day":{},"night":{}},retained=True)
        self.app.set_auto_day_night(True)
        self.assertTrue(self.app._jobs.empty())
        self.app._accept_home_profile({"mode":"night","day":{},"night":{}})
        job=self.app._jobs.get_nowait()
        self.assertEqual(job[3],"AUTO_PROFILE")
        self.app.set_auto_day_night(False)
        self.app.set_auto_day_night(True)
        self.assertIsNot(self.app._home_profile,job[6])
        self.assertEqual(self.app._home_profile,job[6])
        self.app._adapt_home_profile(job[6],job[5])
        self.assertEqual(self.app.event_log.snapshot()["rows"][-1]["reason"],"Режим, профиль или настройки изменились до выполнения")
        self.assertTrue(self.app._jobs.empty())
        self.app._jobs.task_done()
        self.assertTrue(self.app.globals["auto_day_night"])
        with self.app._mutex:
            self.assertFalse(self.app._apply_global_policy(global_policy(self.store.read())))

    def test_live_adaptive_interval_persists_and_reschedules(self):
        original=deepcopy(self.settings)
        bindings=self.store.path.read_bytes()
        self.app._next_adaptive=1900
        self.assertEqual(self.app.set_adaptive_interval(1),{"adaptive_interval_minutes":1})
        self.assertEqual(self.settings,{**original,"adaptive_interval_minutes":1})
        self.assertEqual(self.app._next_adaptive,160)
        self.assertEqual(self.build().globals["adaptive_interval_minutes"],1)
        self.assertEqual(self.store.path.read_bytes(),bindings)
        self.app.set_adaptive_interval(60)
        self.assertEqual(self.app._next_adaptive,3700)
        for value in (0,1441,True,1.5,"5"):
            with self.assertRaises(CatalogError):self.app.set_adaptive_interval(value)
        self.supervisor.write.side_effect=OSError("offline")
        with self.assertRaises(OSError):self.app.set_adaptive_interval(5)
        self.assertEqual(self.app.globals["adaptive_interval_minutes"],60)
        self.assertEqual(self.app._next_adaptive,3700)

    def test_ingress_ui_contract(self):
        web=Path(__file__).resolve().parents[1]/"rootfs/app/actions/web"
        js=(web/"app.js").read_text()
        self.assertIn('id="parameters-nav"',(web/"index.html").read_text())
        self.assertIn('api("parameters",{auto_day_night:requested})',js)
        self.assertIn('check.checked=model.auto_day_night===true',js)
