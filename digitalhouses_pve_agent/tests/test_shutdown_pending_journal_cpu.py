"""A missing shutdown completion cannot trigger journal scans forever."""
from __future__ import annotations

from types import SimpleNamespace

from app.shutdown_integration import ShutdownAwareProductionCollectors
from app.state_store import StateStore


class MutableGuestTopology:
    status = "running"

    def poll_guest_status(self):
        return SimpleNamespace(vms={"110": SimpleNamespace(status=self.status)}, lxcs={})

    def guest_payload(self):
        return {
            "vms": {"110": {
                "kind": "vm",
                "guest_id": "110",
                "name": "HAOS",
                "status": self.status,
                "shutdown_timeout_seconds": 120,
            }},
            "lxcs": {},
            "summary": {},
        }


class MissingCompletionTracker:
    def __init__(self):
        self.refreshes = 0
        self._payload = {"guest_last_shutdowns": {"vm": {}, "lxc": {}}}

    def record_guest_inventory(self, names):
        pass

    def payload(self):
        return self._payload

    def refresh_current_guest_shutdowns(self):
        self.refreshes += 1
        return False

    def enrich_guest_last_shutdowns(self, timeouts):
        return False


def test_empty_guest_inventory_only_scans_history_on_first_collection(tmp_path):
    class EmptyTopology:
        def poll_guest_status(self):
            return SimpleNamespace(vms={}, lxcs={})

        def guest_payload(self):
            return {"vms": {}, "lxcs": {}, "summary": {}}

    history = MissingCompletionTracker()
    collector = ShutdownAwareProductionCollectors(
        node_name="pve",
        disk_state_store=StateStore(tmp_path / "empty_disks.json"),
        topology=EmptyTopology(),
        shutdown_history_tracker=history,
    )
    for _ in range(25):
        collector.guests()
    assert history.refreshes == 1


def test_no_indefinite_full_boot_journal_scan_after_missing_shutdown(tmp_path):
    topology = MutableGuestTopology()
    history = MissingCompletionTracker()
    collector = ShutdownAwareProductionCollectors(
        node_name="pve",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        topology=topology,
        shutdown_history_tracker=history,
    )
    collector.guests()
    assert history.refreshes == 1  # initial inventory

    topology.status = "stopped"
    collector.guests()
    assert history.refreshes == 2

    for _ in range(100):
        collector.guests()
    # Only one delayed retry; no 8-9s CPU scan every polling interval.
    assert history.refreshes == 3
    assert collector._pending_guest_shutdowns == {}
    assert collector._pending_guest_history_attempts == {}

    topology.status = "running"
    collector.guests()
    topology.status = "stopped"
    collector.guests()
    assert history.refreshes == 4  # a *new* stop can still be processed
