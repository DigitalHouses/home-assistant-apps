from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.nfs_monitor import NfsFailureMonitor, _enabled_nfs
from app.state_store import StateStore


def epoch(hour: int, minute: int, second: int) -> float:
    # October 10, 2026; UTC+05 is the site timezone.
    return datetime(2026, 10, 9, hour + 19, minute, second, tzinfo=timezone.utc).timestamp()


def record(when: float, message: str, *, source: str, cursor: str) -> dict[str, str]:
    return {
        "__REALTIME_TIMESTAMP": str(int(when * 1_000_000)),
        "__CURSOR": cursor,
        "MESSAGE": message,
        "SYSLOG_IDENTIFIER": source,
        "_TRANSPORT": "kernel" if source == "kernel" else "syslog",
    }


class Bridge:
    def __init__(self):
        self.connected = True
        self.events = []
        self.states = []

    def publish_diagnostic_event(self, payload):
        if not self.connected:
            return False
        self.events.append(payload)
        return True

    def publish_nfs_diagnostics(self, payload):
        if not self.connected:
            return False
        self.states.append(payload)
        return True


def setup(tmp_path: Path, records=None, bridge=None, rrd=None):
    conf = tmp_path / "storage.cfg"
    conf.write_text(
        "nfs: truenas-backups\n"
        "    server 192.168.2.32\n"
        "    export /mnt/tank/backups\n"
        "    content backup\n"
        "nfs: disabled-backups\n"
        "    disable 1\n"
        "    server 192.168.2.33\n"
        "nfs: other-node\n"
        "    nodes otherpve\n"
        "    server 192.168.2.34\n"
        "dir: local\n"
        "    path /var/lib/vz\n"
    )
    messages = records if records is not None else []
    connection = bridge or Bridge()
    ctimes = rrd if rrd is not None else {}
    reader = lambda since, until: [
        item for item in messages
        if since <= int(item["__REALTIME_TIMESTAMP"]) / 1_000_000 <= until
    ]
    watcher = NfsFailureMonitor(
        StateStore(tmp_path / "state.json"),
        node_name="pve",
        bridge=connection,
        config_path=conf,
        journal_reader=reader,
        rrd_reader=lambda now: ctimes,
    )
    return watcher, connection, messages, ctimes


def test_only_enabled_local_nfs_is_monitored(tmp_path):
    mon, _, _, _ = setup(tmp_path)
    assert _enabled_nfs(mon.config_path, "pve") == {"truenas-backups": "192.168.2.32"}


def test_ruslan_timeline_reports_one_outage_not_334(tmp_path):
    first = epoch(1, 4, 31)
    messages = [
        record(first + 10 * n, "storage 'truenas-backups' is not online",
               source="pvestatd", cursor=f"pvestatd-{n}")
        for n in range(334)
    ]
    messages += [
        record(epoch(1, 6, 35), "INFO: task zstd:586537 blocked for more than 122 seconds.",
               source="kernel", cursor="blocked"),
        record(epoch(1, 7, 13), "nfs: server 192.168.2.32 not responding, still trying",
               source="kernel", cursor="nfs-timeout"),
    ]
    watcher, bridge, _, _ = setup(tmp_path, messages)
    watcher.scan(first - 2)
    watcher.scan(first + 2)
    assert bridge.events == []  # One pvestatd observation is not enough.
    watcher.scan(first + 12)
    assert len(bridge.events) == 1
    evt = bridge.events[0]
    assert evt["event_type"] == "storage_nfs_unavailable"
    assert evt["object_id"] == "truenas-backups"
    assert evt["started_at"] == datetime.fromtimestamp(first, timezone.utc).isoformat()
    assert evt["cause"] == "unknown"
    for n in range(4, 335, 2):
        watcher.scan(first + 10 * n)
    assert len(bridge.events) == 1
    assert len(watcher.state["incidents"]) == 1


def test_kernel_nfs_timeout_opens_immediately(tmp_path):
    start = epoch(1, 7, 13)
    messages = [record(start, "nfs: server 192.168.2.32 not responding, still trying",
                       source="kernel", cursor="kernel-1")]
    watcher, bridge, _, _ = setup(tmp_path, messages)
    watcher.scan(start + 1)
    assert [e["event_type"] for e in bridge.events] == ["storage_nfs_unavailable"]
    assert bridge.events[0]["evidence"] == "kernel_nfs_timeout"


def test_unrelated_messages_never_open_incidents(tmp_path):
    start = epoch(1, 4, 31)
    messages = [
        record(start, "storage 'disabled-backups' is not online",
               source="pvestatd", cursor="disabled-1"),
        record(start + 5, "storage 'truenas-backups' is not online",
               source="untrusted", cursor="untrusted"),
        record(start + 10, "nfs: server 192.168.2.34 not responding, still trying",
               source="kernel", cursor="other"),
    ]
    watcher, bridge, _, _ = setup(tmp_path, messages)
    watcher.scan(start + 11)
    assert watcher.state["incidents"] == {}
    assert bridge.events == []


def test_fresh_pve_rrd_confirmed_twice_before_recovery(tmp_path):
    first = epoch(1, 4, 31)
    messages = [
        record(first, "storage 'truenas-backups' is not online",
               source="pvestatd", cursor="p1"),
        record(first + 10, "storage 'truenas-backups' is not online",
               source="pvestatd", cursor="p2"),
    ]
    watcher, bridge, _, ctimes = setup(tmp_path, messages)
    watcher.scan(first + 1)
    watcher.scan(first + 11)
    assert len(bridge.events) == 1

    watcher.scan(first + 50)
    assert len(bridge.events) == 1  # No fresh PVE data.
    ctimes["truenas-backups"] = first + 52
    watcher.scan(first + 55)
    assert len(bridge.events) == 1  # First confirmation only.
    watcher.scan(first + 65)
    assert len(bridge.events) == 1  # Minimum confirmation interval.
    ctimes["truenas-backups"] = first + 75
    watcher.scan(first + 76)
    assert [e["event_type"] for e in bridge.events] == [
        "storage_nfs_unavailable", "storage_nfs_restored"
    ]
    assert bridge.events[-1]["duration_seconds"] == 76
    assert watcher.state["incidents"] == {}


def test_mqtt_outbox_survives_restart_without_repeating_open(tmp_path):
    first = epoch(1, 4, 31)
    messages = [
        record(first, "storage 'truenas-backups' is not online",
               source="pvestatd", cursor="p1"),
        record(first + 10, "storage 'truenas-backups' is not online",
               source="pvestatd", cursor="p2"),
    ]
    bridge = Bridge()
    bridge.connected = False
    watcher, _, _, _ = setup(tmp_path, messages, bridge=bridge)
    watcher.scan(first + 1)
    watcher.scan(first + 11)
    assert len(watcher.state["pending_events"]) == 1

    bridge.connected = True
    watcher, _, _, _ = setup(tmp_path, messages, bridge=bridge)
    watcher.scan(first + 25)
    assert len(bridge.events) == 1
    watcher.scan(first + 35)
    assert len(bridge.events) == 1
    assert watcher.state["pending_events"] == []


def test_no_implicit_recovery_when_journal_fails(tmp_path):
    first = epoch(1, 4, 31)
    messages = [
        record(first, "storage 'truenas-backups' is not online",
               source="pvestatd", cursor="p1"),
        record(first + 10, "storage 'truenas-backups' is not online",
               source="pvestatd", cursor="p2"),
    ]
    watcher, bridge, _, ctimes = setup(tmp_path, messages)
    watcher.scan(first + 1)
    watcher.scan(first + 11)
    ctimes["truenas-backups"] = first + 70
    def fail(since, until):
        raise RuntimeError("journald unavailable")
    watcher.journal_reader = fail
    import pytest
    with pytest.raises(RuntimeError):
        watcher.scan(first + 80)
    assert len(bridge.events) == 1
    assert "truenas-backups" in watcher.state["incidents"]
