"""PBS Agent 0.1.0 data, state, event and DH Sync contract tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.collector import collect, age_hours, last_run
from app.config import load_config
from app.events import transitions
from app.mqtt import discovery, instance_id
from app.state import StateStore

ROOT = Path(__file__).resolve().parents[1]


def config_text():
    return """
[general]
instance_id = pbs_home
log_level = info
[mqtt]
host = 192.0.2.1
port = 1883
[pbs]
datastores = pbs-home
[monitor]
poll_seconds = 300
backup_rules = pbs-home|-|vm/2222|24
sync_rules = push-home|24
warning_percent = 80
critical_percent = 90
"""


class FakePBS:
    def __init__(self, now: int):
        self.now = now
        self.snapshots = [
            {"backup-type": "vm", "backup-id": "2222", "backup-time": now - 3600}
        ]
        self.sync_status = "OK"
        self.sync_time = now - 3600
        self.used = 500
        self.backend = None
        self.pull_status = None

    def task_list(self, limit=100):
        return list(getattr(self, "tasks", []))

    def get(self, path, **params):
        if path == "version":
            return {"version": "4.2.11"}
        if path == "config/datastore":
            return [{"name": "pbs-home", "path": "/", "gc-schedule": "sun 04:00",
                     "backend": self.backend}]
        if path == "admin/datastore/pbs-home/namespace":
            return [{"ns": "archive"}]
        if path == "admin/datastore/pbs-home/groups":
            if params.get("ns") == "archive":
                return [{"backup-type": "ct", "backup-id": "1221",
                         "last-backup": self.now - 7200, "backup-count": 3}]
            return [{"backup-type": "vm", "backup-id": "2222",
                     "last-backup": self.now - 3600, "backup-count": 7}]
        if path == "admin/datastore/pbs-home/status":
            return {"total": 1000, "used": self.used, "avail": 1000 - self.used}
        if path == "admin/datastore/pbs-home/snapshots":
            return self.snapshots
        if path == "admin/datastore/pbs-home/rrd":
            return list(getattr(self, "rrd", []))
        if path == "admin/sync":
            records = [{"id": "push-home", "sync-direction": "push",
                        "last-run-state": self.sync_status,
                        "last-run-upid": "UPID:pve:test", "last-run-endtime": self.sync_time}]
            if self.pull_status is not None:
                records.append({"id": "b2-copy", "sync-direction": "pull",
                                "store": "pbs-home", "schedule": "daily",
                                "last-run-state": self.pull_status,
                                "last-run-upid": "UPID:pbs:syncjob:b2-copy",
                                "last-run-endtime": self.now - 3600})
            return records
        if path == "admin/verify":
            return [{"id": "verify-home", "last-run-state": "OK"}]
        if path == "admin/prune":
            return [{"id": "prune-home", "last-run-state": "OK"}]
        if path == "admin/datastore/pbs-home/gc":
            return {"last-run-state": "OK", "last-run-endtime": self.now}
        raise AssertionError("unexpected source " + path)


class PBSAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.ini = self.folder / "native.conf"
        self.ini.write_text(config_text(), encoding="utf-8")
        self.config = load_config(self.ini)
        self.now = 1731920400
        self.api = FakePBS(self.now)

    def sample(self):
        with patch("app.collector.zfs_pools", return_value={"status": "HEALTHY", "pools": [{"pool": "backup", "health": "ONLINE"}]}):
            return collect(self.config, self.api, now=self.now)

    def test_native_ini_has_no_pbs_credentials(self):
        self.assertEqual(self.config.datastores, ("pbs-home",))
        self.assertEqual(self.config.backup_rules[0].group, "vm/2222")
        self.assertEqual(self.config.sync_rules[0].job_id, "push-home")
        self.assertFalse(any(x.startswith("pbs_token") or x.startswith("pbs_ca")
                             or x == "pbs_url" for x in self.config.__dataclass_fields__))
        from app.config import KEYS
        self.assertEqual([key for key in KEYS if "token" in key], [])

    def test_healthy_scan_is_supported_by_sources(self):
        data = self.sample()
        self.assertEqual(data["status"], "HEALTHY")
        self.assertEqual(data["datastores"][0]["used_percent"], 50.0)
        self.assertEqual(data["backups"][0]["status"], "OK")
        self.assertEqual(data["sync_jobs"][0]["status"], "OK")
        self.assertEqual(data["summary"]["push_jobs"], 1)
        self.assertEqual(data["problems"], [])

    def test_never_backed_up_is_no_snapshot_and_deduplicated(self):
        self.api.snapshots = []
        state = self.sample()
        self.assertEqual(state["status"], "CRITICAL")
        self.assertEqual(state["backups"][0]["status"], "NO_SNAPSHOT")
        store = StateStore(self.folder / "events.json")
        events = transitions(state, store)
        self.assertEqual([e["payload"]["event_type"] for e in events], ["backup_overdue"])
        self.assertEqual(transitions(state, store), [])
        self.api.snapshots = [{"backup-type": "vm", "backup-id": "2222", "backup-time": self.now - 100}]
        restored = transitions(self.sample(), store)
        self.assertEqual([e["payload"]["event_type"] for e in restored], ["backup_recovered"])

    def test_failed_push_and_overdue_then_recovery(self):
        self.api.sync_status = "ERROR"
        self.api.sync_time = self.now - 100000
        issue = self.sample()
        events = transitions(issue, StateStore(self.folder / "events.json"))
        self.assertIn("sync_failed", {e["payload"]["event_type"] for e in events})
        self.assertIn("sync_overdue", {e["payload"]["event_type"] for e in events})
        self.assertEqual(issue["status"], "CRITICAL")
        self.api.sync_status = "OK"
        self.api.sync_time = self.now - 100
        recovered = transitions(self.sample(), StateStore(self.folder / "events.json"))
        self.assertEqual(
            [x["payload"]["event_type"] for x in recovered].count("sync_recovered"), 2
        )

    def test_low_space_and_zfs_critical(self):
        self.api.used = 950
        with patch("app.collector.zfs_pools", return_value={"status": "DEGRADED", "pools": [{"pool": "backup", "health": "DEGRADED"}]}):
            result = collect(self.config, self.api, now=self.now)
        self.assertEqual(result["status"], "CRITICAL")
        self.assertEqual(
            {x["type"] for x in result["problems"]},
            {"disk_space_low", "zfs_pool_degraded"},
        )

    def test_api_failure_never_green(self):
        class Down:
            def get(self, path, **params):
                from app.collector import SourceError
                raise SourceError("PBS local CLI failed")
        with patch("app.collector.zfs_pools", return_value={"status": "NOT_APPLICABLE", "pools": []}):
            result = collect(self.config, Down(), now=self.now)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertIsNone(result["pbs_version"])
        self.assertEqual(result["problems"][0]["type"], "service_unavailable")

    def test_failed_completed_task_produces_factual_problem(self):
        self.api.tasks = [
            {"upid": "UPID:pbs:111:222:333:backup:abc:",
             "worker_type": "backup", "status": "ERROR: client disconnected",
             "endtime": self.now - 120},
            {"upid": "UPID:pbs:111:222:333:backup:xyz:",
             "worker_type": "backup", "status": "OK",
             "endtime": self.now - 60},
        ]
        data = self.sample()
        self.assertEqual(data["status"], "DEGRADED")
        self.assertEqual(len(data["backup_sessions"]["failed_tasks"]), 1)
        self.assertEqual(
            [x["type"] for x in data["problems"]],
            ["backup_failed"],
        )

    def test_running_task_is_not_failure(self):
        self.api.tasks = [
            {"upid": "UPID:pbs:111:222:333:backup:abc:",
             "worker_type": "backup", "status": None}
        ]
        data = self.sample()
        self.assertEqual(data["backup_sessions"]["active"], 1)
        self.assertNotIn("backup_failed", [p["type"] for p in data["problems"]])

    def test_unavailable_task_cli_keeps_remaining_sources_observable(self):
        from app.collector import SourceError
        def unavailable(limit=100):
            raise SourceError("PBS native task list failed (exit 255)")
        self.api.task_list = unavailable
        data = self.sample()
        self.assertEqual(data["status"], "UNAVAILABLE")
        self.assertEqual(data["pbs_version"], "4.2.11")
        self.assertEqual(data["datastores"][0]["status"], "AVAILABLE")
        self.assertIn("backup tasks: PBS native task list failed",
                      " ".join(data["errors"]))

    def test_mqtt_connect_disconnect_updates_status_immediately(self):
        from app.mqtt import Publisher
        import types
        publisher = Publisher(self.config)
        published = []
        class FakeTransport:
            def publish(self, topic, payload, qos, retain):
                published.append((topic, qos, retain))
            def subscribe(self, topic, qos):
                published.append((topic, qos, False))
        publisher.client = FakeTransport()
        changes = []
        publisher.on_connection_change = lambda state, reason: changes.append((state, reason))
        accepted = types.SimpleNamespace(is_failure=False)
        denied = types.SimpleNamespace(is_failure=True)
        accepted.__str__ = lambda: "Success" if False else "ignored"
        publisher._on_connect(publisher.client, None, None, accepted, None)
        self.assertEqual(changes[-1], ("CONNECTED", None))
        self.assertTrue(any(topic.endswith("/sync") and qos == 1 and retain
                            for topic, qos, retain in published))
        publisher._on_disconnect(publisher.client, None, None, "Unspecified error", None)
        self.assertEqual(changes[-1], ("DISCONNECTED", "Unspecified error"))
        publisher._on_connect(publisher.client, None, None, denied, None)
        self.assertEqual(changes[-1][0], "DISCONNECTED")

    def test_dh_sync_identity_and_ha_entities(self):
        self.assertEqual(instance_id(self.config), "pbs_home")
        payload = discovery(self.config)
        components = payload["components"]
        for key in ("hostname", "ip", "version", "health", "problem",
                    "backup_event", "storage_event", "maintenance_event", "sync_event"):
            self.assertIn(key, components)
        self.assertEqual(components["health"]["default_entity_id"], "sensor.dh_pbs_agent_health")
        self.assertEqual(components["backup_event"]["platform"], "event")
        self.assertEqual(len(payload["device"]["identifiers"]), 1)

    def test_dynamic_identity_other_home_and_auto_entity_markers(self):
        from app.mqtt import discovery, job_component_key
        from app.config import load_config
        house = self.folder / "other-home.conf"
        house.write_text("[general]\ninstance_id=mountain_home\n[mqtt]\nhost=broker\n"
                         "[pbs]\ndatastores=vault-archive,vault-media\n", encoding="utf-8")
        cfg = load_config(house)
        sample = {"maintenance_jobs": [
            {"type": "Verify", "id": "weekly-remote", "status": "OK", "schedule": "sun 07:00"},
            {"type": "Prune", "id": "cleanup-custom", "status": "FAILED", "schedule": "04:00"},
        ]}
        home = discovery(self.config, sample)
        remote = discovery(cfg, sample)
        self.assertEqual(home["components"]["health"]["default_entity_id"],
                         "sensor.dh_pbs_agent_health")
        self.assertEqual(home["components"]["health"]["unique_id"],
                         "dh_pbs_agent_pbs_home_health")
        self.assertEqual(remote["components"]["health"]["unique_id"],
                         "dh_pbs_agent_mountain_home_health")
        self.assertIn('"pbs_product": "digitalhouses_pbs_agent"',
                      remote["components"]["health"]["json_attributes_template"])
        self.assertIn('"pbs_section": "health"',
                      remote["components"]["health"]["json_attributes_template"])
        stores = [item for item in remote["components"].values()
                  if item.get("name", "").startswith("vault-")]
        self.assertEqual(len(stores), 6)  # three metrics per datastore, includes numeric GiB
        for item in stores:
            self.assertIn('"pbs_section": "datastore"', item["json_attributes_template"])
        jobs = {key: value for key, value in remote["components"].items()
                if key.startswith("job_")}
        self.assertEqual(len(jobs), 2)
        verify = jobs[job_component_key("Verify", "weekly-remote")]
        self.assertEqual(verify["name"], "Проверка копий · weekly-remote")
        self.assertEqual(verify["platform"], "sensor")
        self.assertIn('"pbs_section": "job"', verify["json_attributes_template"])
        self.assertIn("value_json.maintenance_jobs", verify["value_template"])
        self.assertIn("mountain_home", verify["unique_id"])
        self.assertEqual(len(remote["device"]["identifiers"]), 1)
        self.assertNotEqual(remote["device"]["identifiers"], home["device"]["identifiers"])
        self.assertNotEqual(job_component_key("Verify", "x-y"),
                            job_component_key("Verify", "x_y"))

    def test_russian_discovery_names_preserve_stable_mqtt_identity(self):
        parts = discovery(self.config, {"maintenance_jobs": [
            {"type": "Verify", "id": "job-serzhan", "status": "OK"}
        ]})["components"]
        expected_names = {
            "hostname": "Имя сервера",
            "ip": "IP-адрес",
            "version": "Версия агента",
            "health": "Состояние PBS",
            "last_collection": "Последний успешный опрос",
            "backup_last_success": "Последняя успешная резервная копия",
            "backup_age_hours": "Возраст резервной копии",
            "sync_state": "Синхронизация копий",
            "sync_last_success": "Последняя успешная синхронизация",
            "zfs_pool_health": "Состояние ZFS",
            "problem": "Проблема PBS",
            "backup_event": "События резервного копирования",
            "sync_event": "События синхронизации",
            "storage_event": "События хранилищ",
            "maintenance_event": "События обслуживания",
            "view_backup_groups_limit": "Групп резервных копий",
            "view_task_events_limit": "Последних событий",
        }
        for key, label in expected_names.items():
            self.assertEqual(parts[key]["name"], label)
            self.assertEqual(parts[key]["unique_id"], "dh_pbs_agent_pbs_home_" + key)
        for key, component in parts.items():
            if key.startswith("datastore_"):
                self.assertTrue(component["name"].startswith("pbs-home · "))
                self.assertIn("pbs_section", component["json_attributes_template"])
        from app.mqtt import job_component_key
        job = parts[job_component_key("Verify", "job-serzhan")]
        self.assertEqual(job["name"], "Проверка копий · job-serzhan")
        self.assertEqual(job["unique_id"],
                         "dh_pbs_agent_pbs_home_" + job_component_key("Verify", "job-serzhan"))
        self.assertIn('pbs_job_type', job["json_attributes_template"])
        self.assertEqual(parts["health"]["default_entity_id"], "sensor.dh_pbs_agent_health")
        self.assertEqual(parts["problem"]["default_entity_id"], "binary_sensor.dh_pbs_agent_problem")

    def test_dynamic_job_discovery_and_expired_job_cleanup(self):
        import threading
        from unittest.mock import Mock
        from app.mqtt import Publisher, job_component_key
        from app.state import StateStore, ViewLimits
        pub = Publisher.__new__(Publisher)
        pub.config = self.config
        pub.base = "DigitalHouses/Global/digitalhouses_pbs_agent/pbs_home"
        pub.discovery_topic = "homeassistant/device/dh_pbs_agent_pbs_home/config"
        pub.view_limits = ViewLimits()
        pub._state_lock = threading.Lock()
        pub._known_jobs = set()
        pub._discovery_primed = False
        pub.job_registry = StateStore(self.folder / "discovery_jobs.json")
        pub.last_state = None
        pub.last_ack_at = None
        pub.connected = True
        pub.client = Mock()
        pub.client.publish.return_value.rc = 0
        pub.client.publish.return_value.is_published.return_value = True
        basic = {"status": "HEALTHY", "maintenance_jobs": [
            {"type": "Verify", "id": "site-verify", "status": "OK", "schedule": "daily"}
        ]}
        self.assertTrue(pub.state(basic))
        published = pub.client.publish.call_args_list
        self.assertEqual(len(published), 6)  # discovery, state, four existing trees
        config = json.loads(published[0].args[1])
        self.assertIn(job_component_key("Verify", "site-verify"), config["components"])
        self.assertEqual(pub.job_registry.load()["jobs"], [["Verify", "site-verify"]])
        pub.client.reset_mock()
        self.assertTrue(pub.state(basic))
        self.assertEqual(pub.client.publish.call_count, 5)
        replacement = {"status": "HEALTHY", "maintenance_jobs": [
            {"type": "Verify", "id": "different-home", "status": "OK"}
        ]}
        pub.client.reset_mock()
        self.assertTrue(pub.state(replacement))
        sent = pub.client.publish.call_args_list
        self.assertEqual(len(sent), 7)
        removal = json.loads(sent[0].args[1])
        self.assertEqual(removal["components"][job_component_key("Verify", "site-verify")],
                         {"platform": "sensor"})
        current = json.loads(sent[1].args[1])
        self.assertNotIn(job_component_key("Verify", "site-verify"), current["components"])
        self.assertIn(job_component_key("Verify", "different-home"), current["components"])
        self.assertEqual(pub.job_registry.load()["jobs"], [["Verify", "different-home"]])

    def test_pve_style_dynamic_progress_metadata_and_s3_fallback(self):
        from app.mqtt import discovery
        from app.config import load_config
        path = self.folder / "many-stores.conf"
        path.write_text("[mqtt]\nhost=broker\n[pbs]\ndatastores=lab-archive,pbs-media\n",
                        encoding="utf-8")
        sensors = discovery(load_config(path))["components"]
        for store in ("lab-archive", "pbs-media"):
            key = "datastore_" + store.replace("-", "_") + "_used_percent"
            entry = sensors[key]
            self.assertEqual(entry["platform"], "sensor")
            self.assertIn("pbs_metric", entry["json_attributes_template"])
            self.assertIn("'total_gib':", entry["json_attributes_template"])
            self.assertIn("'used_gib':", entry["json_attributes_template"])
            self.assertIn("'pbs_health':", entry["json_attributes_template"])
            self.assertIn("'pbs_backend':", entry["json_attributes_template"])
            self.assertIn(store, entry["name"])
            self.assertEqual(entry["default_entity_id"], "sensor.dh_pbs_agent_" + key)
        view = (ROOT / "dashboards/ru/13_pbs.yaml").read_text(encoding="utf-8")
        for key in ("card_name", "card_secondary", "card_color",
                    "card_icon", "card_percent"):
            self.assertIn(f"state_attr(entity, '{key}')", view)
            self.assertIn("'" + key + "':", sensors["datastore_lab_archive_used_percent"]["json_attributes_template"])
        from app.main import display_state
        sample = self.sample()
        store = display_state(sample, self.config, "192.0.2.1")["datastores"][0]
        self.assertEqual(store["card_name"], "pbs-home · занято 50.0%")
        self.assertEqual(store["card_color"], "green")
        self.assertEqual(store["card_icon"], "mdi:database-check")
        sample["datastores"][0]["backend"] = "S3"
        s3 = display_state(sample, self.config, "192.0.2.1")["datastores"][0]
        self.assertEqual(s3["card_color"], "grey")
        self.assertEqual(s3["card_secondary"], "S3 · объём не определён")
        self.assertIn("'bar_size': 'medium'", view)
        self.assertIn("'tap_action': {'action': 'more-info', 'entity': entity}", view)

    def test_ui_is_standalone_with_dynamic_store_and_job_names(self):
        view = (ROOT / "dashboards/ru/13_pbs.yaml").read_text(encoding="utf-8")
        self.assertIn("type: custom:auto-entities", view)
        self.assertIn("custom:entity-progress-card-template", view)
        self.assertIn("pbs_section') == 'datastore'", view)
        self.assertIn("pbs_metric') == 'used_percent'", view)
        for name in ("backup", "jobs", "history"):
            self.assertIn(f"state_attr('sensor.dh_pbs_agent_{name}_tree', 'text')", view)
        self.assertNotIn("as_local(as_datetime", view)
        self.assertNotIn("events[:event_limit]", view)
        self.assertNotIn("for g in groups[:group_limit]", view)
        for site in ("pbs-serzhan", "dh-weekly-serzhan", "pbs-core"):
            self.assertNotIn(site, view)
        self.assertIn("number.dh_pbs_agent_backup_groups_limit", view)
        self.assertIn("number.dh_pbs_agent_task_events_limit", view)

    def test_packages_are_portable_and_view_standalone(self):
        view = (ROOT / "dashboards/ru/13_pbs.yaml").read_text("utf-8")
        notifications = (ROOT / "packages/locales/ru/dh_pbs_agent_notification_local_package.yaml").read_text("utf-8")
        self.assertIn("path: dh_pbs_agent", view)
        self.assertIn("sections:", view)
        self.assertNotIn("dh_dashboard_admin_only", view)
        self.assertNotIn("DH-Dashboard", view)
        self.assertIn("trigger: event.received", notifications)
        self.assertIn("action: persistent_notification.create", notifications)
        self.assertNotIn("tojson", notifications)
        self.assertNotIn("192.168.", notifications)

    def test_dashboard_uses_compact_pve_style_tree_not_wide_tables(self):
        view = (ROOT / "dashboards/ru/13_pbs.yaml").read_text(encoding="utf-8")
        self.assertEqual(view.count("<pre style="), 4)
        for kind in ("backup", "jobs", "history"):
            self.assertIn(f"sensor.dh_pbs_agent_{kind}_tree", view)
        self.assertIn("heading: Хранилища PBS", view)
        self.assertIn("custom:entity-progress-card-template", view)
        self.assertNotIn("ns.lines | join", view)
        self.assertNotIn("| Datastore | Заполнено", view)

    def test_view_limits_native_mqtt_numbers_and_persistence(self):
        from app.state import StateStore, ViewLimits
        from app.main import display_state
        from app.config import KEYS
        self.assertNotIn("dashboard_backup_groups_limit", KEYS)
        self.assertNotIn("dashboard_task_events_limit", KEYS)
        path = self.folder / "view_limits.json"
        limits = ViewLimits(StateStore(path))
        self.assertEqual(limits.snapshot(), {"backup_groups": 10, "task_events": 10})
        self.assertNotIn("view_limits", display_state(self.sample(), self.config, "192.0.2.1"))
        self.assertEqual(limits.update("backup_groups", 24)["backup_groups"], 24)
        self.assertEqual(limits.update("task_events", 30)["task_events"], 30)
        self.assertEqual(ViewLimits(StateStore(path)).snapshot(), {
            "backup_groups": 24, "task_events": 30
        })
        with self.assertRaises(ValueError):
            limits.update("backup_groups", 81)
        with self.assertRaises(ValueError):
            limits.update("task_events", 51)
        with self.assertRaises(ValueError):
            limits.update("task_events", 1.5)
        self.assertEqual(limits.snapshot(), {"backup_groups": 24, "task_events": 30})
        comps = discovery(self.config)["components"]
        for key, upper in (("backup_groups", 80), ("task_events", 50)):
            number = comps["view_" + key + "_limit"]
            self.assertEqual(number["platform"], "number")
            self.assertEqual(number["entity_category"], "config")
            self.assertEqual(number["min"], 1)
            self.assertEqual(number["max"], upper)
            self.assertEqual(number["step"], 1)
            self.assertEqual(number["mode"], "box")
            self.assertEqual(number["command_topic"].split("/")[-1], key)
            self.assertIn("value_json.view_limits." + key, number["value_template"])
        self.assertEqual(len(discovery(self.config)["device"]["identifiers"]), 1)
        self.assertIn("'view_limits': value_json.view_limits",
                      comps["health"]["json_attributes_template"])

    def test_mqtt_number_changes_republish_state_without_service_restart(self):
        import threading
        import types
        from unittest.mock import Mock
        from app.mqtt import Publisher
        from app.state import StateStore, ViewLimits
        store = StateStore(self.folder / "view_limits.json")
        pub = Publisher.__new__(Publisher)
        pub.base = "DigitalHouses/Global/digitalhouses_pbs_agent/pbs_home"
        pub.view_limits = ViewLimits(store)
        pub._state_lock = threading.Lock()
        pub.last_state = {"status": "HEALTHY", "view_limits": pub.view_limits.snapshot()}
        transport = Mock()
        def send(key, value, *, retained=False):
            topic = pub.base + "/set/view/" + key
            message = types.SimpleNamespace(topic=topic, payload=value.encode(), retain=retained)
            pub._on_message(transport, None, message)
        send("backup_groups", "13.0")
        self.assertEqual(pub.view_limits.snapshot()["backup_groups"], 13)
        self.assertEqual(pub.last_state["view_limits"]["backup_groups"], 13)
        state_publish = [call for call in transport.publish.call_args_list
                         if call.args[0].endswith("/state")]
        self.assertEqual(json.loads(state_publish[-1].args[1])["view_limits"]["backup_groups"], 13)
        self.assertEqual(sum("/tree/" in call.args[0] for call in transport.publish.call_args_list), 4)
        self.assertTrue(transport.publish.call_args.kwargs["retain"])
        self.assertEqual(ViewLimits(store).snapshot()["backup_groups"], 13)
        count = transport.publish.call_count
        for invalid in ("-1", "81", "12.4", "NaN", "not_a_number"):
            send("backup_groups", invalid)
        send("not_a_setting", "10")
        send("backup_groups", "7", retained=True)
        self.assertEqual(transport.publish.call_count, count)
        self.assertEqual(pub.view_limits.snapshot()["backup_groups"], 13)
        send("task_events", "15")
        self.assertEqual(pub.view_limits.snapshot()["task_events"], 15)

    def test_maintenance_tree_has_schedule_above_last_run(self):
        from app.view import render_trees
        data = {"maintenance_jobs": [{
            "type": "Verify", "id": "dh-weekly", "schedule": "sun 07:00",
            "last_run_at": "2026-11-21T21:02:00+00:00", "status": "OK",
        }]}
        result = render_trees(data, "Asia/Almaty", {})["jobs"]
        self.assertIn("└─ Verify (1)", result)
        self.assertIn("   └─ 🕒 sun 07:00", result)
        self.assertIn("      └─ 🟢 dh-weekly · OK · 22.11 02:02", result)

    def test_backup_guest_identity_from_actual_pbs_worker_only(self):
        from app.collector import _backup_guest, _task_history
        examples = [
            ({"worker_id": "pbs-serzhan:vm-1234"}, "VM1234"),
            ({"worker_id": "pbs-serzhan:vm/1234"}, "VM1234"),
            ({"worker-id": "pbs-serzhan:ct/1221"}, "CT1221"),
            ({"worker_id": "ignored-format",
              "upid": r"UPID:pbs:00011F53:011064D4:00000336:667B4F54:backup:pbs\x2dbackup\x3avm-168:root@pam:"}, "VM168"),
            ({"worker-id": "archive:ct-1221"}, "CT1221"),
            ({"upid": r"UPID:pbs:00011F53:011064D4:00000336:667B4F54:backup:pbs\x2dbackup\x3avm-168:pve-user@pbs:"}, "VM168"),
            ({"upid": r"UPID:pbs:00011F53:011064D4:00000336:667B4F54:backup:store\x3act-4321:user@pbs:"}, "CT4321"),
            ({"upid": "UPID:pbs:1:2:3:backup:z"}, None),
            ({"worker_id": "store:vm-ABC"}, None),
            ({"worker_id": "store:vm-1234-extra"}, None),
            ({"worker_id": "vm-1234"}, None),
            ({"worker_id": "store:host-archiver"}, None),
            ({"upid": r"UPID:pbs:1:2:3:4:verify:store\x3avm-1234:root@pam:"}, None),
            ({"upid": r"UPID:pbs:1:2:3:4:backup:some-store\x3ajob-1234:root@pam:"}, None),
        ]
        for row, expected in examples:
            with self.subTest(row=row):
                self.assertEqual(_backup_guest(row), expected)
        now = self.now
        rows = [
            {"worker_type": "backup", "worker_id": "any-datastore:vm-1234",
             "upid": "UPID:pbs:unimportant", "starttime": now - 60,
             "endtime": now - 30, "status": "OK"},
            {"worker_type": "backup", "upid": "UPID:pbs:1:2:3:backup:z",
             "starttime": now - 90, "endtime": now - 80, "status": "OK"},
            {"worker_type": "verify", "worker_id": "any-datastore:vm-1234",
             "starttime": now - 120, "endtime": now - 100, "status": "OK"},
        ]
        history = _task_history(rows)
        self.assertEqual([row["type"] for row in history],
                         ["Backup", "Backup", "Verify"])
        self.assertEqual([row["guest"] for row in history],
                         ["VM1234", None, None])
        self.assertEqual(history[0]["duration_seconds"], 30)

    def test_native_pbs_snapshot_manifest_supplies_real_increment(self):
        from app.collector import PBSClient
        from datetime import datetime, timezone
        from unittest.mock import Mock
        start = 1795309200
        timestamp = datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_dir = self.folder / "datastore" / "vm" / "2222" / timestamp
        manifest_dir.mkdir(parents=True)
        blob = manifest_dir / "index.json.blob"
        blob.write_bytes(b"PBS_NATIVE_BLOB_NOT_JSON")
        decoded = {
            "backup-type": "vm", "backup-id": "2222", "backup-time": start,
            "unprotected": {"chunk_upload_stats": {
                "compressed_size": 118111600, "size": 107374182400,
                "count": 123, "duplicates": 122,
            }},
        }
        output = json.dumps(decoded) + "size: 1542\nencryption: none\n"
        with patch("app.collector.subprocess.run",
                   return_value=Mock(stdout=output, returncode=0)) as run:
            result = PBSClient.snapshot_upload_bytes(
                str(self.folder / "datastore"), "", "vm", "2222", start)
        self.assertEqual(result, 118111600)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:6], ["proxmox-backup-debug", "inspect",
                                    "file", "--decode", "-", str(blob)])
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_native_pbs_manifest_nested_namespace_identity_safety(self):
        from app.collector import PBSClient, SourceError
        from datetime import datetime, timezone
        from unittest.mock import Mock
        start = 1795309200
        timestamp = datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        folder = (self.folder / "datastore" / "ns" / "prod"
                  / "ns" / "home" / "ct" / "1221" / timestamp)
        folder.mkdir(parents=True)
        (folder / "index.json.blob").write_bytes(b"PBS")
        decoded = {"backup-type": "ct", "backup-id": "1221",
                   "backup-time": start, "unprotected": {"chunk_upload_stats": {"compressed_size": 0}}}
        with patch("app.collector.subprocess.run",
                   return_value=Mock(stdout=json.dumps(decoded) + "size: 1")):
            self.assertEqual(PBSClient.snapshot_upload_bytes(
                str(self.folder / "datastore"), "prod/home", "ct", "1221", start), 0)
        with self.assertRaises(SourceError):
            PBSClient.snapshot_upload_bytes(str(self.folder), "../outside", "ct", "1221", start)
        with self.assertRaises(SourceError):
            PBSClient.snapshot_upload_bytes(str(self.folder), "", "ct", "../../etc", start)
        with patch("app.collector.subprocess.run",
                   return_value=Mock(stdout=json.dumps({**decoded, "backup-id": "other"}))):
            with self.assertRaisesRegex(SourceError, "identity/time mismatch"):
                PBSClient.snapshot_upload_bytes(
                    str(self.folder / "datastore"), "prod/home", "ct", "1221", start)

    def test_actual_manifest_beats_broken_snapshot_api(self):
        from app.collector import _backup_upload_stats, _task_history
        from unittest.mock import Mock
        start = self.now - 60
        task_rows = [{"worker_type": "backup", "worker_id": "pbs-home:vm/2222",
                      "starttime": start, "endtime": start + 32, "status": "OK"}]
        history = _task_history(task_rows)
        groups = [{"datastore": "pbs-home", "namespace": "", "group": "vm/2222",
                   "last_backup_at": history[0]["started_at"]}]
        old = self.api.get
        def getter(path, **params):
            if path.endswith("/snapshots"):
                return [{"backup-type": "vm", "backup-id": "2222", "backup-time": start}]
            if path.endswith("/snapshot-information"):
                raise AssertionError("API endpoint must not be called when native manifest succeeds")
            return old(path, **params)
        self.api.get = getter
        self.api.snapshot_upload_bytes = Mock(return_value=118111600)
        cache = {}
        _backup_upload_stats(self.api, history, groups, cache, {"pbs-home": "/mnt/datastore/pbs-home"})
        self.assertEqual(history[0]["upload_status"], "OK")
        self.assertEqual(history[0]["uploaded_compressed_bytes"], 118111600)
        self.assertEqual(groups[0]["last_uploaded_compressed_bytes"], 118111600)
        self.api.snapshot_upload_bytes.assert_called_once_with(
            "/mnt/datastore/pbs-home", "", "vm", "2222", start)
        second = _task_history(task_rows)
        _backup_upload_stats(self.api, second, groups, cache, {"pbs-home": "/mnt/datastore/pbs-home"})
        self.assertEqual(second[0]["uploaded_compressed_bytes"], 118111600)
        self.assertEqual(self.api.snapshot_upload_bytes.call_count, 1)

    def test_manifest_and_api_errors_are_diagnostic_not_fake_sizes(self):
        from app.collector import _backup_upload_stats, _task_history, SourceError
        from unittest.mock import Mock
        started = self.now - 60
        history = _task_history([{
            "worker_type": "backup", "worker_id": "pbs-home:ct/1221",
            "starttime": started, "endtime": started + 11, "status": "OK",
        }])
        rows = [{"datastore": "pbs-home", "namespace": "", "group": "ct/1221"}]
        original = self.api.get
        def getter(path, **params):
            if path.endswith("/snapshots"):
                return [{"backup-type": "ct", "backup-id": "1221",
                         "backup-time": started}]
            if path.endswith("/snapshot-information"):
                raise SourceError("PBS API status 500")
            return original(path, **params)
        self.api.get = getter
        self.api.snapshot_upload_bytes = Mock(side_effect=SourceError("local manifest absent"))
        _backup_upload_stats(self.api, history, rows, {}, {"pbs-home": "/mnt/pbs-home"})
        self.assertEqual(history[0]["upload_status"], "API_ERROR")
        self.assertIn("local manifest absent", history[0]["upload_error"])
        self.assertIn("PBS API status 500", history[0]["upload_error"])
        self.assertNotIn("uploaded_compressed_bytes", history[0])
        self.assertNotIn("last_uploaded_compressed_bytes", rows[0])

    def test_native_manifest_error_falls_back_to_existing_pbs_api(self):
        from app.collector import _backup_upload_stats, _task_history, SourceError
        from unittest.mock import Mock
        start = self.now - 60
        history = _task_history([{
            "worker_type": "backup", "worker_id": "pbs-home:vm/2222",
            "starttime": start, "endtime": start + 32, "status": "OK",
        }])
        groups = [{"datastore": "pbs-home", "namespace": "", "group": "vm/2222"}]
        old = self.api.get
        def getter(path, **params):
            if path.endswith("/snapshots"):
                return [{"backup-type": "vm", "backup-id": "2222", "backup-time": start}]
            if path.endswith("/snapshot-information"):
                return {"upload-statistics": {"compressed-size": 90000000}}
            return old(path, **params)
        self.api.get = getter
        self.api.snapshot_upload_bytes = Mock(side_effect=SourceError("manifest unavailable"))
        _backup_upload_stats(self.api, history, groups, {}, {"pbs-home": "/mnt/datastore/pbs-home"})
        self.assertEqual(history[0]["uploaded_compressed_bytes"], 90000000)
        self.assertEqual(history[0]["upload_status"], "OK")

    def test_compressed_upload_increment_uses_exact_snapshot_statistics(self):
        from app.collector import _backup_upload_stats, _task_history
        start = self.now - 40
        rows = [{
            "worker_type": "backup", "worker_id": "pbs-home:vm-2222",
            "upid": "UPID:pbs:1:2:3:4:backup:pbs-home:root@pam:",
            "starttime": start, "endtime": start + 32, "status": "OK"
        }]
        history = _task_history(rows)
        groups = [{"datastore": "pbs-home", "namespace": "", "group": "vm/2222"}]
        snapshots = [{"backup-type": "vm", "backup-id": "2222", "backup-time": start}]
        calls = []
        saved = self.api.get

        def matching_get(path, **params):
            if path.endswith("/snapshots"):
                return snapshots if not params.get("ns") else []
            if path.endswith("/snapshot-information"):
                calls.append((path, dict(params)))
                return {"upload-statistics": {
                    "size": 107374182400,
                    "compressed-size": 118111600,
                    "count": 35, "duplicates": 0
                }}
            return saved(path, **params)

        self.api.get = matching_get
        cache = {}
        _backup_upload_stats(self.api, history, groups, cache)
        self.assertEqual(history[0]["uploaded_compressed_bytes"], 118111600)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], {
            "backup-type": "vm", "backup-id": "2222", "backup-time": start,
            "ns": None
        })
        history_again = _task_history(rows)
        _backup_upload_stats(self.api, history_again, groups, cache)
        self.assertEqual(history_again[0]["uploaded_compressed_bytes"], 118111600)
        self.assertEqual(len(calls), 1, "must reuse immutable stats on next poll")

        # Deleted snapshots cannot reuse a stale cached value.
        snapshots.clear()
        empty = _task_history(rows)
        _backup_upload_stats(self.api, empty, groups, cache)
        self.assertNotIn("uploaded_compressed_bytes", empty[0])

    def test_upload_increment_is_present_in_normal_collected_history(self):
        start = self.now - 60
        self.api.tasks = [{"worker_type": "backup", "worker_id": "pbs-home:vm/2222",
                           "starttime": start, "endtime": start + 30,
                           "status": "OK", "upid": "UPID:pbs:1:2:3:4:backup:ignored:root@pam:"}]
        self.api.snapshots = [{"backup-type": "vm", "backup-id": "2222",
                               "backup-time": start}]
        old = self.api.get
        def getter(path, **params):
            if path.endswith("/snapshots") and params.get("ns") == "archive":
                return []
            if path.endswith("/groups") and not params.get("ns"):
                return [{"backup-type": "vm", "backup-id": "2222",
                         "last-backup": start, "backup-count": 1}]
            if path.endswith("/snapshot-information"):
                return {"upload-statistics": {"compressed-size": 118111600,
                                               "size": 107374182400}}
            return old(path, **params)
        self.api.get = getter
        cache = {}
        with patch("app.collector.zfs_pools", return_value={"status": "HEALTHY", "pools": []}):
            result = collect(self.config, self.api, now=self.now, upload_cache=cache)
        self.assertEqual(result["status"], "HEALTHY")
        self.assertEqual(result["task_history"][0]["guest"], "VM2222")
        self.assertEqual(result["task_history"][0]["uploaded_compressed_bytes"], 118111600)
        self.assertEqual(result["backup_groups"][0]["last_uploaded_compressed_bytes"], 118111600)
        from app.view import render_trees
        group_tree = render_trees(result, "Asia/Almaty", {})["backup"]
        self.assertIn("vm/2222 · 1 коп. · +0.11 GiB", group_tree)
        self.assertTrue(cache)

    def test_upload_increment_requires_unique_matching_successful_snapshot(self):
        from app.collector import _backup_upload_stats, _task_history
        start = self.now - 50
        rows = [
            {"worker_type": "backup", "worker_id": "pbs-home:vm-2222",
             "starttime": start, "endtime": start + 30, "status": "OK"},
            {"worker_type": "backup", "worker_id": "other-store:vm-2222",
             "starttime": start, "endtime": start + 30, "status": "OK"},
            {"worker_type": "backup", "worker_id": "pbs-home:ct-1221",
             "starttime": start, "endtime": None, "status": ""},
            {"worker_type": "backup", "starttime": start,
             "endtime": start + 20, "status": "OK"},
        ]
        history = _task_history(rows)
        groups = [{"datastore": "pbs-home", "namespace": "", "group": "vm/2222"},
                  {"datastore": "other-store", "namespace": "", "group": "vm/2222"}]
        old = self.api.get
        info_calls = []
        def getter(path, **params):
            if path.endswith("/snapshots"):
                if "other-store" in path:
                    return [{"backup-type": "vm", "backup-id": "2222", "backup-time": start}]
                return [{"backup-type": "vm", "backup-id": "2222", "backup-time": start},
                        {"backup-type": "vm", "backup-id": "2222", "backup-time": start+1}]
            if path.endswith("/snapshot-information"):
                info_calls.append(path)
                return {"upload-statistics": {"compressed-size": 11000000}}
            return old(path, **params)
        self.api.get = getter
        _backup_upload_stats(self.api, history, groups, {})
        self.assertNotIn("uploaded_compressed_bytes", history[0],
                         "two possible snapshots must not be assigned")
        self.assertEqual(history[1]["uploaded_compressed_bytes"], 11000000,
                         "same VM in another datastore is an independent identity")
        self.assertNotIn("uploaded_compressed_bytes", history[2],
                         "running backup has no final transfer size")
        self.assertNotIn("uploaded_compressed_bytes", history[3],
                         "unknown worker guest cannot get fabricated size")
        self.assertEqual(len(info_calls), 1)

    def test_same_snapshot_not_attributed_to_two_nearby_tasks(self):
        from app.collector import _backup_upload_stats, _task_history
        now = self.now
        rows = [
            {"worker_type": "backup", "worker_id": "pbs-home:vm/2222",
             "starttime": now - 110, "endtime": now - 90, "status": "OK"},
            {"worker_type": "backup", "worker_id": "pbs-home:vm/2222",
             "starttime": now - 70, "endtime": now - 50, "status": "OK"},
        ]
        snapshots = [{"backup-type": "vm", "backup-id": "2222",
                      "backup-time": now - 75}]
        old = self.api.get
        info_calls = []
        def getter(path, **params):
            if path.endswith("/snapshots"):
                return snapshots
            if path.endswith("/snapshot-information"):
                info_calls.append(path)
                return {"upload-statistics": {"compressed-size": 120000000}}
            return old(path, **params)
        self.api.get = getter
        history = _task_history(rows)
        _backup_upload_stats(self.api, history, [
            {"datastore": "pbs-home", "namespace": "", "group": "vm/2222"}], {})
        self.assertTrue(all("uploaded_compressed_bytes" not in x for x in history))
        self.assertEqual(info_calls, [])

    def test_upload_increment_unknown_or_missing_stats_is_not_zero(self):
        from app.collector import _backup_upload_stats, _task_history, SourceError
        start = self.now - 60
        rows = [{"worker_type": "backup", "worker_id": "pbs-home:vm-2222",
                 "starttime": start, "endtime": start + 32, "status": "OK"}]
        groups = [{"datastore": "pbs-home", "namespace": "", "group": "vm/2222"}]
        old = self.api.get
        def getter(path, **params):
            if path.endswith("/snapshots"):
                return [{"backup-type": "vm", "backup-id": "2222", "backup-time": start}]
            if path.endswith("/snapshot-information"):
                return {"upload-statistics": {"size": 107374182400}}
            return old(path, **params)
        self.api.get = getter
        history = _task_history(rows)
        _backup_upload_stats(self.api, history, groups, {})
        self.assertNotIn("uploaded_compressed_bytes", history[0])
        def failed(path, **params):
            if path.endswith("/snapshot-information"):
                raise SourceError("unavailable")
            return getter(path, **params)
        self.api.get = failed
        history = _task_history(rows)
        _backup_upload_stats(self.api, history, groups, {})
        self.assertNotIn("uploaded_compressed_bytes", history[0])

    def test_upload_tree_shows_increment_not_snapshot_total(self):
        from app.view import _size, render_trees
        self.assertEqual(_size(118111600), " · +0.11 GiB")
        self.assertEqual(_size(1848210), " · +1.8 MiB")
        self.assertEqual(_size(0), " · +0 B")
        self.assertEqual(_size(None), "")
        data = {"task_history": [
            {"started_at": "2026-11-21T21:03:00+00:00", "type": "Backup",
             "guest": "VM2222", "uploaded_compressed_bytes": 118111600,
             "duration_seconds": 32, "status": "OK"},
            {"started_at": "2026-11-21T21:02:00+00:00", "type": "Backup",
             "guest": "VM1000", "duration_seconds": 12, "status": "OK"},
        ]}
        tree = render_trees(data, "Asia/Almaty", {})["history"]
        self.assertIn("Backup VM2222 · +0.11 GiB · 32 с · OK", tree)
        self.assertIn("Backup VM1000 · 12 с · OK", tree)
        self.assertNotIn("100 GiB", tree)

    def test_task_history_groups_by_home_assistant_local_day(self):
        from app.view import render_trees
        events = [
            {"started_at": "2026-11-21T21:03:00+00:00",
             "type": "Backup", "status": "OK", "duration_seconds": 32},
            {"started_at": "2026-11-21T18:03:00+00:00",
             "type": "Prune", "status": "OK", "duration_seconds": 1},
        ]
        data = {"task_history": events}
        almaty = render_trees(data, "Asia/Almaty", {})["history"]
        utc = render_trees(data, "UTC", {})["history"]
        self.assertIn("📅 22.11.2026 (1)", almaty)
        self.assertIn("02:03 · Backup", almaty)
        self.assertIn("📅 21.11.2026 (1)", almaty)
        self.assertIn("23:03 · Prune", almaty)
        self.assertIn("📅 21.11.2026 (2)", utc)
        self.assertNotIn("22.11.2026", utc)
        missing = render_trees(data, None, {})["history"]
        self.assertIn("⚠ Часовой пояс HA не получен; временно UTC", missing)

    def test_task_history_labels_local_day_counts_and_guests(self):
        from app.view import render_trees
        events = [
            {"started_at": f"2026-11-21T21:0{i}:00+00:00",
             "type": "Backup", "guest": f"VM{i}", "status": "OK",
             "duration_seconds": i+1}
            for i in range(5, -1, -1)
        ]
        data = {"task_history": events, "task_history_status": "AVAILABLE"}
        limited = render_trees(data, "Asia/Almaty", {"task_events": 2})["history"]
        self.assertIn("📅 22.11.2026 (6)", limited)
        self.assertIn("Backup VM5", limited)
        self.assertNotIn("Backup VM1", limited)
        self.assertIn("└─ Ещё 4 событий", limited)

    def test_dashboard_uses_correct_percentage_and_independent_limits(self):
        view = (ROOT / "dashboards/ru/13_pbs.yaml").read_text(encoding="utf-8")
        self.assertIn("state_attr(entity, 'card_name')", view)
        self.assertIn("state_attr(entity, 'card_secondary')", view)
        self.assertIn("state_attr(entity, 'card_percent')", view)
        self.assertIn("state_attr(entity, 'card_color')", view)
        self.assertNotIn("d.available_bytes / d.total_bytes", view)
        from app.view import render_trees
        data = {"backup_groups": [{"group": "vm/2222", "datastore": "store",
                 "snapshot_count": 1, "status": "OK", "age_hours": 1},
                {"group": "vm/3333", "datastore": "store",
                 "snapshot_count": 1, "status": "OK", "age_hours": 1}]}
        content = render_trees(data, "Asia/Almaty", {"backup_groups": 1})["backup"]
        self.assertIn("Ещё 1 групп", content)
        self.assertIn("vm/2222", content)
        self.assertNotIn("vm/3333", content)

    def test_history_has_more_than_twelve_real_events(self):
        self.api.tasks = [
            {"upid": f"UPID:pbs:1:2:3:prune:{i}", "worker_type": "prune",
             "starttime": self.now - 60 * i,
             "endtime": self.now - 60 * i + 10, "status": "OK"}
            for i in range(25)
        ]
        sample = self.sample()
        self.assertEqual(len(sample["task_history"]), 25)

    def test_native_s3_and_pull_job_visible_with_real_result(self):
        self.api.backend = "bucket=pbs-b2,client=backblaze,type=s3"
        self.api.pull_status = "OK"
        data = self.sample()
        self.assertEqual(data["datastores"][0]["backend"], "S3")
        self.assertEqual(data["sync_jobs"][0]["id"], "push-home")
        self.assertEqual(data["pull_sync_jobs"][0]["id"], "b2-copy")
        records = {(j["type"], j["id"]): j for j in data["maintenance_jobs"]}
        self.assertEqual(records[("S3 Sync", "b2-copy")]["status"], "OK")
        self.assertEqual(records[("S3 Sync", "b2-copy")]["schedule"], "daily")
        self.assertEqual(data["status"], "HEALTHY")
        self.api.pull_status = "ERROR"
        degraded = self.sample()
        self.assertEqual(degraded["status"], "DEGRADED")
        self.assertEqual(
            next(j["status"] for j in degraded["maintenance_jobs"] if j["type"] == "S3 Sync"),
            "FAILED",
        )

    def test_non_s3_local_pull_not_labeled_cloud(self):
        self.api.pull_status = "OK"
        data = self.sample()
        self.assertEqual(data["datastores"][0]["backend"], "LOCAL")
        self.assertTrue(any(j["type"] == "Pull Sync" for j in data["maintenance_jobs"]))
        self.assertFalse(any(j["type"] == "S3 Sync" for j in data["maintenance_jobs"]))

    def test_dashboard_inventory_includes_namespaces_and_monitored_status(self):
        sample = self.sample()
        self.assertEqual(sample["backup_groups_status"], "COMPLETE")
        groups = {row["group"]: row for row in sample["backup_groups"]}
        self.assertEqual(groups["vm/2222"]["snapshot_count"], 7)
        self.assertEqual(groups["vm/2222"]["status"], "OK")
        self.assertEqual(groups["ct/1221"]["namespace"], "archive")
        self.assertEqual(groups["ct/1221"]["status"], "OK")
        self.assertEqual(groups["ct/1221"]["freshness_source"], "automatic")
        self.assertEqual(groups["ct/1221"]["freshness_hours"], 36.0)
        jobs = {(j["type"], j["id"]): j for j in sample["maintenance_jobs"]}
        self.assertEqual(jobs[("Push Sync", "push-home")]["status"], "OK")
        self.assertEqual(jobs[("Verify", "verify-home")]["status"], "OK")
        self.assertEqual(jobs[("Prune", "prune-home")]["status"], "OK")
        self.assertEqual(jobs[("GC", "pbs-home")]["status"], "OK")
        self.assertEqual(jobs[("GC", "pbs-home")]["schedule"], "sun 04:00")

    def test_automatic_freshness_default_override_and_recovery(self):
        from app.collector import AUTO_FRESHNESS_HOURS
        from app.events import transitions
        self.assertEqual(AUTO_FRESHNESS_HOURS, 36.0)
        from app.state import StateStore
        saved = StateStore(self.folder / "auto_freshness_incidents.json")
        original_get = self.api.get
        def stale_groups(path, **params):
            if path.endswith("/groups") and params.get("ns") == "archive":
                return [{"backup-type": "ct", "backup-id": "1221",
                         "last-backup": self.now - 48 * 3600,
                         "backup-count": 3}]
            return original_get(path, **params)
        self.api.get = stale_groups
        first = self.sample()
        found = {x["group"]: x for x in first["backup_groups"]}
        self.assertEqual(found["vm/2222"]["freshness_source"], "configured")
        self.assertEqual(found["vm/2222"]["freshness_hours"], 24)
        self.assertEqual(found["ct/1221"]["freshness_source"], "automatic")
        self.assertEqual(found["ct/1221"]["status"], "OVERDUE")
        self.assertEqual(first["freshness_summary"]["overdue"], 1)
        self.assertEqual(first["status"], "CRITICAL")
        self.assertEqual([x["key"] for x in first["problems"]
                          if x["type"] == "backup_overdue"],
                         ["backup:pbs-home:archive:ct/1221"])
        started = transitions(first, saved)
        self.assertTrue(any(x["payload"]["event_type"] == "backup_overdue" for x in started))
        self.assertEqual(transitions(first, saved), [])
        self.api.get = original_get
        recovered = self.sample()
        self.assertEqual(recovered["freshness_summary"]["ok"], 2)
        ended = transitions(recovered, saved)
        self.assertTrue(any(x["payload"]["event_type"] == "backup_recovered" for x in ended))

    def test_published_ha_timezone_is_retained_and_reformats_tree(self):
        import threading, types
        from unittest.mock import Mock
        from app.mqtt import Publisher, HA_TIMEZONE_TOPIC
        from app.state import StateStore, ViewLimits
        pub = Publisher.__new__(Publisher)
        pub._state_lock = threading.Lock()
        pub.base = "DigitalHouses/Global/digitalhouses_pbs_agent/pbs_home"
        pub.timezone_store = StateStore(self.folder / "ha_timezone.json")
        pub.ha_timezone = None
        pub.view_limits = ViewLimits()
        pub.last_state = {"status": "HEALTHY", "view_limits": pub.view_limits.snapshot(),
                          "task_history": [{
                              "started_at": "2026-11-21T21:03:00+00:00",
                              "type": "Backup", "guest": "VM2222",
                              "status": "OK", "duration_seconds": 32,
                          }]}
        transport = Mock()
        retained = types.SimpleNamespace(
            topic=HA_TIMEZONE_TOPIC, payload=b"Asia/Almaty", retain=True)
        pub._on_message(transport, None, retained)
        self.assertEqual(pub.ha_timezone, "Asia/Almaty")
        self.assertEqual(pub.timezone_store.load()["timezone"], "Asia/Almaty")
        self.assertEqual(pub.last_state["ha_timezone"], "Asia/Almaty")
        sent = [c for c in transport.publish.call_args_list
                if c.args[0].endswith("/tree/history")]
        self.assertEqual(len(sent), 1)
        self.assertIn("02:03", json.loads(sent[0].args[1])["text"])
        self.assertIn("22.11.2026", json.loads(sent[0].args[1])["text"])
        before = transport.publish.call_count
        invalid = types.SimpleNamespace(topic=HA_TIMEZONE_TOPIC,
                                        payload=b"Bad/Unknown_Zone", retain=True)
        pub._on_message(transport, None, invalid)
        self.assertEqual(transport.publish.call_count, before)
        pub._on_message(transport, None, retained)
        self.assertEqual(transport.publish.call_count, before)
        package = (ROOT / "packages/common/dh_pbs_agent_timezone_package.yaml").read_text()
        self.assertIn('payload: "{{ now().tzinfo.key }}"', package)
        self.assertIn('retain: true', package)

    def test_tree_content_is_own_mqtt_payload_not_large_health_attribute(self):
        from app.mqtt import discovery
        parts = discovery(self.config)["components"]
        for name in ("backup", "jobs", "history", "summary"):
            item = parts["tree_" + name]
            self.assertEqual(item["platform"], "sensor")
            self.assertIn("/tree/" + name, item["state_topic"])
            self.assertIn("value_json.text", item["json_attributes_template"])
        health = parts["health"]["json_attributes_template"]
        self.assertNotIn("backup_tree", health)
        self.assertNotIn("history_tree", health)
        self.assertIn("sensor.dh_pbs_agent_summary_tree",
                      (ROOT / "dashboards/ru/13_pbs.yaml").read_text())

    def test_upload_failure_is_diagnostic_not_fabricated_zero(self):
        from app.collector import _backup_upload_stats, _task_history, SourceError
        start = self.now - 60
        rows = [{"worker_type": "backup", "worker_id": "pbs-home:vm/2222",
                 "starttime": start, "endtime": start + 30, "status": "OK"}]
        old = self.api.get
        def broken_detail(path, **params):
            if path.endswith("/snapshots"):
                return [{"backup-type": "vm", "backup-id": "2222",
                         "backup-time": start}]
            if path.endswith("/snapshot-information"):
                raise SourceError("API failed")
            return old(path, **params)
        self.api.get = broken_detail
        hist = _task_history(rows)
        _backup_upload_stats(self.api, hist, [{"datastore": "pbs-home",
             "namespace": "", "group": "vm/2222"}], {})
        self.assertNotIn("uploaded_compressed_bytes", hist[0])
        self.assertEqual(hist[0]["upload_status"], "API_ERROR")

    def test_history_is_actual_tasks_not_fabricated_job_success(self):
        self.api.tasks = [
            {"upid": "UPID:pbs:1:2:3:prune:x", "worker_type": "prune",
             "starttime": self.now - 180, "endtime": self.now - 150, "status": "OK"},
            {"upid": "UPID:pbs:1:2:3:verificationjob:y", "worker_type": "verificationjob",
             "starttime": self.now - 60, "endtime": self.now - 30, "status": "ERROR"},
            {"upid": "UPID:pbs:1:2:3:backup:z", "worker_type": "backup",
             "starttime": self.now - 10, "endtime": None, "status": None},
            {"upid": "UPID:pbs:1:2:3:other:w", "worker_type": "other",
             "starttime": self.now - 40, "endtime": self.now - 20, "status": "OK"},
        ]
        sample = self.sample()
        self.assertEqual(sample["task_history_status"], "AVAILABLE")
        self.assertEqual([x["type"] for x in sample["task_history"]],
                         ["Backup", "Verify", "Prune"])
        self.assertEqual([x["status"] for x in sample["task_history"]],
                         ["RUNNING", "FAILED", "OK"])
        self.assertEqual(sample["task_history"][-1]["duration_seconds"], 30)

    def test_optional_inventory_failure_is_visible_without_fake_healthy_groups(self):
        from app.collector import SourceError
        original = self.api.get
        def broken_namespace(path, **params):
            if path.endswith("/namespace"):
                raise SourceError("not supported")
            return original(path, **params)
        self.api.get = broken_namespace
        sample = self.sample()
        self.assertEqual(sample["status"], "HEALTHY")
        self.assertEqual(sample["backup_groups_status"], "PARTIAL")
        self.assertIn("namespaces pbs-home: not supported", sample["errors"])
        self.assertEqual(sample["backup_groups"][0]["group"], "vm/2222")

    def test_group_list_failure_is_partial_and_not_fabricated(self):
        from app.collector import SourceError
        original = self.api.get
        def broken_groups(path, **params):
            if path.endswith("/groups"):
                raise SourceError("permission or missing directory")
            return original(path, **params)
        self.api.get = broken_groups
        state = self.sample()
        self.assertEqual(state["status"], "HEALTHY")
        self.assertEqual(state["backup_groups_status"], "PARTIAL")
        self.assertEqual(state["backup_groups"], [])
        self.assertTrue(any("groups pbs-home" in err for err in state["errors"]))

    def test_dashboard_contains_real_sources_not_fabricated_example_rows(self):
        from app.mqtt import discovery
        view = (ROOT / "dashboards/ru/13_pbs.yaml").read_text("utf-8")
        for attribute in ("maintenance_jobs", "task_history", "backup_groups"):
            self.assertIn("'" + attribute + "'",
                          discovery(self.config)["components"]["health"]["json_attributes_template"])
        for kind in ("backup", "jobs", "history"):
            self.assertIn(f"state_attr('sensor.dh_pbs_agent_{kind}_tree', 'text')", view)
            self.assertIn("tree_" + kind, discovery(self.config)["components"])
        self.assertNotIn("21.11 02:00", view)
        from app.view import render_trees
        result = render_trees(self.sample(), "Asia/Almaty", {})
        self.assertIn("Последние выполнения PBS", result["history"])
        self.assertIn("Группы резервных копий (", result["backup"])

    def test_systemd_pbs_lock_exception_is_scoped(self):
        unit = (ROOT / "systemd/digitalhouses_pbs_agent.service").read_text("utf-8")
        self.assertIn("User=root", unit)
        self.assertIn("ProtectSystem=full", unit)
        self.assertIn(
            "ReadWritePaths=/var/lib/digitalhouses_pbs_agent /etc/proxmox-backup",
            unit,
        )
        self.assertNotIn("ReadWritePaths=/etc\n", unit)
        self.assertNotIn("ProtectSystem=false", unit)

    def test_last_run_unknown_not_ok(self):
        self.assertEqual(last_run({})["status"], "NEVER_RUN")
        self.assertEqual(last_run({"last-run-state": "garbled"})["status"], "UNKNOWN")
        self.assertIsNone(age_hours(self.now, None))


if __name__ == "__main__":
    unittest.main()
