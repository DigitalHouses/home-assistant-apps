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
        self.assertEqual(len(stores), 4)
        for item in stores:
            self.assertIn('"pbs_section": "datastore"', item["json_attributes_template"])
        jobs = {key: value for key, value in remote["components"].items()
                if key.startswith("job_")}
        self.assertEqual(len(jobs), 2)
        verify = jobs[job_component_key("Verify", "weekly-remote")]
        self.assertEqual(verify["name"], "Verify · weekly-remote")
        self.assertEqual(verify["platform"], "sensor")
        self.assertIn('"pbs_section": "job"', verify["json_attributes_template"])
        self.assertIn("value_json.maintenance_jobs", verify["value_template"])
        self.assertIn("mountain_home", verify["unique_id"])
        self.assertEqual(len(remote["device"]["identifiers"]), 1)
        self.assertNotEqual(remote["device"]["identifiers"], home["device"]["identifiers"])
        self.assertNotEqual(job_component_key("Verify", "x-y"),
                            job_component_key("Verify", "x_y"))

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
        self.assertEqual(len(published), 2)
        config = json.loads(published[0].args[1])
        self.assertIn(job_component_key("Verify", "site-verify"), config["components"])
        self.assertEqual(pub.job_registry.load()["jobs"], [["Verify", "site-verify"]])
        pub.client.reset_mock()
        self.assertTrue(pub.state(basic))
        self.assertEqual(pub.client.publish.call_count, 1)
        replacement = {"status": "HEALTHY", "maintenance_jobs": [
            {"type": "Verify", "id": "different-home", "status": "OK"}
        ]}
        pub.client.reset_mock()
        self.assertTrue(pub.state(replacement))
        sent = pub.client.publish.call_args_list
        self.assertEqual(len(sent), 3)
        removal = json.loads(sent[0].args[1])
        self.assertEqual(removal["components"][job_component_key("Verify", "site-verify")],
                         {"platform": "sensor"})
        current = json.loads(sent[1].args[1])
        self.assertNotIn(job_component_key("Verify", "site-verify"), current["components"])
        self.assertIn(job_component_key("Verify", "different-home"), current["components"])
        self.assertEqual(pub.job_registry.load()["jobs"], [["Verify", "different-home"]])

    def test_ui_is_standalone_with_dynamic_store_and_job_names(self):
        view = (ROOT / "dashboards/ru/13_pbs.yaml").read_text(encoding="utf-8")
        self.assertNotIn("type: custom:auto-entities", view)
        self.assertNotIn("states.sensor", view)
        self.assertIn("state_attr('sensor.dh_pbs_agent_health',", view)
        self.assertIn("~ d.name]", view)
        self.assertIn("~ j.id ~", view)
        self.assertIn("store_prefix = (g.datastore ~ '/') if (ds | count) > 1 else ''", view)
        self.assertIn("detail_prefix = '│  │  ' if not loop.last else '│     '", view)
        for hardcoded in ("pbs-serzhan", "dh-weekly-serzhan", "pbs-core"):
            self.assertNotIn(hardcoded, view)
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
        self.assertEqual(view.count("<pre style="), 3)
        self.assertIn("├─ Datastore", view)
        self.assertIn("Группы резервных копий", view)
        self.assertIn("Контроль свежести", view)
        self.assertIn("Последние выполнения", view)
        self.assertIn("S3 Sync", view)
        self.assertIn("ns.lines | join('\\n')", view)
        self.assertNotIn("| Datastore | Заполнено", view)
        self.assertNotIn("content: >-", view)

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
        self.assertEqual(json.loads(transport.publish.call_args.args[1])["view_limits"]["backup_groups"], 13)
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
        view = (ROOT / "dashboards/ru/13_pbs.yaml").read_text(encoding="utf-8")
        self.assertIn("type_indent ~ branch ~ ' 🕒 ' ~ schedule", view)
        self.assertIn("type_indent ~ child_indent ~ '└─ ' ~ icon ~ ' ' ~ j.id", view)
        self.assertNotIn("when ~ ' · ' ~ schedule", view)
        self.assertIn("shown_kinds.items", view)
        self.assertIn("j.schedule or 'без расписания'", view)
        self.assertIn("as_local(as_datetime(j.last_run_at))", view)

    def test_dashboard_uses_correct_percentage_and_independent_limits(self):
        view = (ROOT / "dashboards/ru/13_pbs.yaml").read_text(encoding="utf-8")
        self.assertIn("d.available_bytes / d.total_bytes", view)
        self.assertIn("free ~ '/' ~ total ~ ' GiB ('", view)
        self.assertIn("detail_prefix ~ '└─ '", view)
        self.assertIn("groups[:group_limit]", view)
        self.assertIn("events[:event_limit]", view)
        self.assertIn("limits.backup_groups | default(10)", view)
        self.assertIn("limits.task_events | default(10)", view)
        self.assertNotIn("без правила", view)

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
        self.assertEqual(groups["ct/1221"]["status"], "NOT_MONITORED")
        jobs = {(j["type"], j["id"]): j for j in sample["maintenance_jobs"]}
        self.assertEqual(jobs[("Push Sync", "push-home")]["status"], "OK")
        self.assertEqual(jobs[("Verify", "verify-home")]["status"], "OK")
        self.assertEqual(jobs[("Prune", "prune-home")]["status"], "OK")
        self.assertEqual(jobs[("GC", "pbs-home")]["status"], "OK")
        self.assertEqual(jobs[("GC", "pbs-home")]["schedule"], "sun 04:00")

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
            self.assertIn("'" + attribute + "'", discovery(self.config)["components"]["health"]["json_attributes_template"])
            self.assertIn("'" + attribute + "'", view)
        self.assertIn("Последние выполнения PBS", view)
        self.assertIn("Группы резервных копий (", view)
        self.assertNotIn("21.11 02:00", view)

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
