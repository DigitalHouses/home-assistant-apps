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

    def task_list(self, limit=100):
        return list(getattr(self, "tasks", []))

    def get(self, path, **params):
        if path == "version":
            return {"version": "4.2.11"}
        if path == "config/datastore":
            return [{"name": "pbs-home", "path": "/"}]
        if path == "admin/datastore/pbs-home/status":
            return {"total": 1000, "used": self.used, "avail": 1000 - self.used}
        if path == "admin/datastore/pbs-home/snapshots":
            return self.snapshots
        if path == "admin/sync":
            return [{"id": "push-home", "sync-direction": "push",
                     "last-run-state": self.sync_status,
                     "last-run-upid": "UPID:pve:test", "last-run-endtime": self.sync_time}]
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

    def test_last_run_unknown_not_ok(self):
        self.assertEqual(last_run({})["status"], "NEVER_RUN")
        self.assertEqual(last_run({"last-run-state": "garbled"})["status"], "UNKNOWN")
        self.assertIsNone(age_hours(self.now, None))


if __name__ == "__main__":
    unittest.main()
