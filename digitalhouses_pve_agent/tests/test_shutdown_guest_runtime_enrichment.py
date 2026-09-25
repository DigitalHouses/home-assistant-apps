from types import SimpleNamespace

from app.shutdown_integration import ShutdownAwareProductionCollectors
from app.state_store import StateStore


class FakeTopology:
    def poll_guest_status(self):
        return SimpleNamespace(
            vms={},
            lxcs={"333": SimpleNamespace(status="running")},
        )

    def guest_payload(self):
        return {
            "vms": {},
            "lxcs": {
                "333": {
                    "kind": "lxc",
                    "guest_id": "333",
                    "name": "NetAlertX",
                    "status": "running",
                    "shutdown_timeout_seconds": 30,
                    "shutdown_order": 50,
                    "onboot": True,
                }
            },
            "summary": {},
        }


class FakeShutdownHistoryTracker:
    def __init__(self):
        self.enriched_with = None
        self._payload = {
            "guest_last_shutdowns": {
                "vm": {},
                "lxc": {
                    "333": {
                        "kind": "lxc",
                        "guest_id": "333",
                        "started_at": "2026-09-26T01:10:32+05:00",
                        "finished_at": "2026-09-26T01:10:44+05:00",
                        "duration_seconds": 12,
                        "timeout_seconds": None,
                        "timeout_ratio": None,
                        "assessment": "unknown",
                        "result": "clean",
                        "forced": False,
                        "source": "guest_shutdown",
                    }
                },
            }
        }

    def payload(self):
        return self._payload

    def refresh_current_guest_shutdowns(self):
        return False

    def enrich_guest_last_shutdowns(self, guest_timeouts):
        self.enriched_with = dict(guest_timeouts)
        item = self._payload["guest_last_shutdowns"]["lxc"]["333"]
        item["timeout_seconds"] = 30
        item["timeout_ratio"] = 0.4
        item["assessment"] = "ok"
        return True


def test_guest_collector_enriches_latest_shutdown_fact_before_presentation(tmp_path):
    tracker = FakeShutdownHistoryTracker()
    collector = ShutdownAwareProductionCollectors(
        node_name="pve",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        topology=FakeTopology(),
        shutdown_history_tracker=tracker,
    )

    sample = collector.guests()

    assert tracker.enriched_with == {("lxc", "333"): 30}
    guest = sample.data["lxcs"]["333"]
    assert guest["last_shutdown_duration_seconds"] == 12
    assert guest["last_shutdown_timeout_seconds"] == 30
    assert guest["last_shutdown_timeout_ratio"] == 0.4
    assert guest["last_shutdown_assessment"] == "ok"
