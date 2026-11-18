"""Backup Jobs HOME contract: coverage, per-guest evidence, deduplicated events."""
import json

import pytest

from app.backup_jobs import (
    PveBackupMonitor, parse_guest_log, select_members, summarize_task,
)
from app.state_store import StateStore


def test_members_all_exclusions_and_explicit_and_pool():
    guests = {100: {}, 101: {}, 2223: {}}
    assert select_members({"all": 1, "exclude": "2223"}, guests) == [100, 101]
    assert select_members({"vmid": "100,2223"}, guests) == [100, 2223]
    assert select_members({"pool": "office"}, guests, {101}) == [101]
    with pytest.raises(ValueError):
        select_members({"pool": "office"}, guests)
    with pytest.raises(ValueError):
        select_members({}, guests)


def test_guest_log_only_real_success():
    parsed = parse_guest_log([
        "INFO: Starting Backup of VM 100 (qemu)",
        "INFO: Finished Backup of VM 100 (00:00:02)",
        "INFO: Starting Backup of VM 101 (lxc)",
        "ERROR: Backup of VM 101 failed - permission denied",
    ])
    assert parsed[100]["status"] == "OK"
    assert parsed[101] == {"status": "FAILED", "reason": "permission denied"}


def test_missing_guest_is_not_ok():
    result, members = summarize_task(
        [100, 101], {"status": "stopped", "exitstatus": "OK"},
        ["INFO: starting new backup job: vzdump 100 101 --mode snapshot",
         "INFO: Finished Backup of VM 100 (00:00:02)"],
    )
    assert result == "PARTIAL"
    assert [item["status"] for item in members] == ["OK", "MISSING"]
    result, members = summarize_task(
        [100, 101], {"status": "stopped", "exitstatus": "OK"}, None,
    )
    assert result == "UNKNOWN"
    assert all(item["status"] == "UNKNOWN" for item in members)


class FakePve:
    def __init__(self):
        self.upid = "UPID:pve:00000001:00000002:00000064:vzdump::root@pam:"
        self.status = "OK"
        self.logs = [
            "INFO: Finished Backup of VM 100 (00:00:01)",
            "ERROR: Backup of VM 101 failed - disk error",
        ]
        self.jobs = [{
            "id": "daily", "all": 1, "exclude": "2223",
            "enabled": 1, "schedule": "02:00", "storage": "pbs-home",
            "next-run": 2000000000,
            "last-run-upid": self.upid,
        }]

    def __call__(self, argv):
        path = argv[2]
        if path == "/cluster/resources":
            return json.dumps([
                {"vmid": 100, "name": "HA", "type": "qemu", "node": "pve"},
                {"vmid": 101, "name": "DB", "type": "lxc", "node": "pve"},
                {"vmid": 2223, "name": "PBS", "type": "qemu", "node": "pve"},
                {"vmid": 5000, "name": "other node", "type": "qemu", "node": "other"},
            ])
        if path == "/cluster/backup":
            return json.dumps(self.jobs)
        if path.endswith("/status"):
            return json.dumps({"status": "stopped", "exitstatus": self.status, "endtime": 1711001000})
        if path.endswith("/log"):
            return json.dumps([{"t": row} for row in self.logs])
        raise AssertionError(path)


def monitor(tmp_path, fake):
    return PveBackupMonitor(
        StateStore(tmp_path / "backup.json"), runner=fake,
        node="pve", now=lambda: 1711002000.0, excluded_vmids=(2223,),
        jobstate_dir=tmp_path,
    )


def test_failed_guest_partial_and_recovered_without_repeated_events(tmp_path):
    fake = FakePve()
    m = monitor(tmp_path, fake)
    state, events = m.scan()
    assert state["status"] == "PROBLEM"
    assert state["summary"]["excluded"] == 1
    assert state["summary"]["covered"] == 2
    assert state["jobs"][0]["status"] == "PARTIAL"
    assert [member["status"] for member in state["jobs"][0]["members"]] == ["OK", "FAILED"]
    assert {e["event_type"] for e in events} == {"backup_job_failed", "backup_guest_failed"}
    assert m.scan()[1] == []
    fake.upid = "UPID:pve:00000001:00000002:00000065:vzdump::root@pam:"
    fake.jobs[0]["last-run-upid"] = fake.upid
    fake.logs = [
        "INFO: Finished Backup of VM 100 (00:00:01)",
        "INFO: Finished Backup of VM 101 (00:00:01)",
    ]
    state, events = m.scan()
    assert state["jobs"][0]["status"] == "OK"
    assert {e["event_type"] for e in events} == {"backup_job_recovered", "backup_guest_recovered"}
    assert m.scan()[1] == []


def test_uncovered_new_guest_and_coverage_recovery(tmp_path):
    fake = FakePve()
    fake.jobs[0]["vmid"] = "100"
    fake.jobs[0].pop("all")
    fake.jobs[0].pop("exclude")
    m = monitor(tmp_path, fake)
    payload, events = m.scan()
    assert payload["summary"]["uncovered"] == 1
    assert any(e["event_type"] == "backup_guest_uncovered" and e["vmid"] == 101 for e in events)
    assert not any(e["event_type"] == "backup_guest_uncovered" and e["vmid"] == 2223 for e in events)
    fake.jobs[0]["vmid"] = "100,101"
    state, events = m.scan()
    assert state["summary"]["uncovered"] == 0
    assert any(e["event_type"] == "backup_guest_recovered" and e["vmid"] == 101 for e in events)


def test_failed_job_without_log_proves_job_failure_not_guest_failure():
    state, members = summarize_task(
        [100], {"status": "stopped", "exitstatus": "ERROR: storage unavailable"}, None,
    )
    assert state == "FAILED"
    assert members[0]["status"] == "UNKNOWN"


def test_skipped_guest_is_incomplete():
    status, members = summarize_task(
        [100, 101], {"status": "stopped", "exitstatus": "ERROR"},
        [
            "INFO: starting new backup job: vzdump 100 101 --mode snapshot",
            "INFO: Finished Backup of VM 100 (00:00:01)",
            "INFO: skipping Backup of VM 101 -- exclude flag",
        ],
    )
    assert status == "PARTIAL"
    assert members[1]["status"] == "SKIPPED"


def test_missing_without_execution_manifest_remains_unknown():
    state, members = summarize_task(
        [100, 101], {"status": "stopped", "exitstatus": "OK"},
        ["INFO: Finished Backup of VM 100 (00:00:02)"],
    )
    assert state == "UNKNOWN"
    assert members[1]["status"] == "UNKNOWN"


def test_api_failure_unavailable_not_healthy(tmp_path):
    def failing(_argv):
        raise OSError("API unavailable")

    m = monitor(tmp_path, failing)
    state, events = m.scan()
    assert state["status"] == "UNAVAILABLE"
    assert state["summary"] is None
    assert state["jobs"] == []
    assert not events


def test_backup_ha_resources_on_existing_view():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    view = (root / "dashboards/ru/10_pve_proxmox.yaml").read_text("utf-8")
    package = (root / "packages/locales/ru/dh_pve_agent_notification_local_package.yaml").read_text("utf-8")
    assert "path: dh_pve_agent" in view
    assert "sensor.dh_pve_agent_backup_monitor" in view
    assert "event.dh_pve_agent_backup" in package
    for event in (
        "backup_job_failed", "backup_job_missed", "backup_job_recovered",
        "backup_guest_failed", "backup_guest_missing",
        "backup_guest_uncovered", "backup_guest_recovered",
    ):
        assert "id: " + event in package
