from __future__ import annotations

import json
import time

from app.backup_discovery import backup_components
from app.backup_history import (
    BackupHistory, BackupReader, build_run, parse_log,
)
from app.config import MqttConfig
from app.identity import HostIdentity
from app.machine_event_outbox import MachineEventOutbox
from app.mqtt_bridge import MqttEvents
from app.runtime_settings import RuntimeSettings
from app.state_store import StateStore
from app.topics import build_topics


def _task(upid="UPID:pve:1:2:3:vzdump::root@pam:", status="OK", started=None):
    start = int(time.time()) if started is None else started
    row = {"upid": upid, "type": "vzdump", "starttime": start, "status": status}
    if status != "RUNNING":
        row["endtime"] = start + 18
    return row


def _lines():
    return [
        "INFO: starting new backup job: vzdump 2222 1221 --storage pbs-serzhan",
        "INFO: Job 'home-nightly' triggered by schedule '03:00'.",
        "INFO: Starting Backup of VM 2222 (qemu)",
        "INFO: VM Name: Home Assistant",
        "INFO: transferred 9.00 GiB in 16 seconds",
        "INFO: Finished Backup of VM 2222 (00:00:16)",
        "INFO: Starting Backup of VM 1221 (lxc)",
        "INFO: CT Name: Ansible",
        "INFO: archive file size: 1.00GB",
        "INFO: Finished Backup of VM 1221 (00:00:02)",
        "INFO: Backup job finished successfully",
    ]


def _monitor(tmp_path):
    return BackupHistory(
        StateStore(tmp_path / "history.json"),
        MachineEventOutbox(StateStore(tmp_path / "events.json")),
    )


def test_real_pve_84_pbs_vm_and_lxc_log_shape():
    # Real PVE 8.4.21 log shape (2026-11-22); CT completion is a test fixture.
    lines = [
        "INFO: starting new backup job: vzdump 1237 10004 10001 1011 99100 99134 "
        "777 1221 7000 2222 --node pve --quiet 1 --mode snapshot --storage pbs-serzhan",
        "INFO: Starting Backup of VM 777 (qemu)",
        "INFO: VM Name: digitalhouses.vip",
        "INFO: backup was done incrementally, reused 32.00 GiB (100%)",
        "INFO: transferred 32.00 GiB in 19 seconds (1.7 GiB/s)",
        "INFO: Finished Backup of VM 777 (00:00:21)",
        "INFO: Starting Backup of VM 1011 (lxc)",
        "INFO: CT Name: digitalhouses.vip",
        "INFO: root.pxar: had to backup 20.744 MiB of 2.452 GiB "
        "(compressed 4.843 MiB) in 10.51 s (average 1.973 MiB/s)",
        "INFO: root.pxar: backup was done incrementally, reused 2.432 GiB (99.2%)",
        "INFO: Finished Backup of VM 1011 (00:00:15)",
    ]
    parsed = parse_log(lines, {"dh-backup-critical-daily": "Критический"})
    assert parsed["job_id"] is None  # Proxmox log does not expose scheduler job ID.
    assert parsed["label"] == "vzdump · pbs-serzhan"
    vm, ct = parsed["guests"]
    assert (vm["kind"], vm["size_kind"], vm["size_gib"]) == ("VM", "processed", 32.0)
    assert (ct["kind"], ct["size_kind"], ct["size_gib"]) == ("CT", "processed", 2.45)
    result = build_run(_task(), parsed)
    assert result["size_kind"] == "processed"
    assert result["size_gib"] == 34.45
    # Reused GiB and compressed MiB are not used as newly stored PBS bytes.
    assert "uploaded_gib" not in result


def test_multiple_pbs_lxc_archive_streams_sum_logical_totals():
    lines = [
        "INFO: Starting Backup of VM 1011 (lxc)",
        "INFO: root.pxar: had to backup 50 MiB of 2.0 GiB (compressed 5 MiB)",
        "INFO: mp0.pxar: had to backup 10 MiB of 3.0 GiB (compressed 1 MiB)",
        "INFO: Finished Backup of VM 1011 (00:00:12)",
    ]
    guest = parse_log(lines, {})["guests"][0]
    assert guest["size_gib"] == 5.0
    assert guest["size_kind"] == "processed"


def test_parse_pve_log_and_size_semantics():
    parsed = parse_log(_lines(), {"home-nightly": "Ночное копирование"})
    assert parsed["job_id"] == "home-nightly"
    assert parsed["label"] == "Ночное копирование"
    assert [(g["kind"], g["id"], g["status"]) for g in parsed["guests"]] == [
        ("VM", "2222", "success"), ("CT", "1221", "success")]
    assert parsed["guests"][0]["size_kind"] == "processed"
    assert parsed["guests"][0]["size_gib"] == 9
    assert parsed["guests"][1]["size_kind"] == "archive"
    assert parsed["guests"][1]["size_gib"] == 0.93
    # Never sum processed logical bytes and actual local archive sizes.
    assert build_run(_task(), parsed)["size_gib"] is None


def test_guest_failure_and_skips_are_separate_and_job_failed():
    log = [
        "INFO: skip external VMs: 700, 701",
        "INFO: Starting Backup of VM 1221 (lxc)",
        "ERROR: Backup of VM 1221 failed - no such volume",
    ]
    parsed = parse_log(log, {})
    run = build_run(_task(status="job errors"), parsed)
    assert run["status"] == "failed"
    assert [g["status"] for g in run["guests"]] == ["skipped", "skipped", "failed"]
    assert run["guests"][2]["error"] == "no such volume"
    assert run["label"] == "vzdump"


def test_fail_closed_when_finished_task_lacks_result():
    row = _task(status="")
    run = build_run(row, parse_log([], {}))
    assert run["status"] == "unknown"
    assert run["size_gib"] is None


def test_running_task_and_unconfirmed_guest_completion():
    row = _task(status="RUNNING")
    parsed = parse_log(["INFO: Starting Backup of VM 2222 (qemu)"], {})
    assert build_run(row, parsed)["status"] == "running"
    row["status"] = "OK"
    row["endtime"] = row["starttime"] + 60
    run = build_run(row, parsed)
    assert run["status"] == "success"
    assert run["guests"][0]["status"] == "unknown"


def test_single_kind_all_guest_sizes_may_be_aggregated():
    log = [
        "INFO: Starting Backup of VM 101 (qemu)",
        "INFO: archive file size: 1.00GB",
        "INFO: Finished Backup of VM 101 (00:00:05)",
        "INFO: Starting Backup of VM 102 (qemu)",
        "INFO: archive file size: 2.00GB",
        "INFO: Finished Backup of VM 102 (00:00:08)",
    ]
    run = build_run(_task(), parse_log(log, {}))
    assert run["size_gib"] == 2.79
    assert run["size_kind"] == "archive"


def test_reader_is_strictly_read_only_uses_task_log_and_caches_completed():
    calls = []
    task = _task()
    def api(argv):
        calls.append(argv)
        assert argv[:2] == ["pvesh", "get"]
        path = argv[2]
        if path == "/cluster/backup":
            return [{"id": "home-nightly", "comment": "Ночное копирование"}]
        if path == "/nodes/pve/tasks":
            assert argv[argv.index("--source") + 1] == "all"
            return [{**task}, {"upid": "OTHER", "type": "vncshell", "starttime": 1}]
        if path.endswith("/log"):
            assert argv[argv.index("--limit") + 1] == "5000"
            return [{"n": n, "t": line} for n, line in enumerate(_lines())]
        raise AssertionError(path)
    reader = BackupReader("pve", api)
    first = reader.read(10)
    second = reader.read(10)
    assert first["coverage"] == second["coverage"] == "available"
    assert first["runs"][0]["label"] == "Ночное копирование"
    assert sum(x[2].endswith("/log") for x in calls) == 1
    assert all(x[1] == "get" for x in calls)


def test_reader_records_missing_log_without_fabricating_guest_success():
    def api(argv):
        if argv[2] == "/cluster/backup":
            return []
        if argv[2] == "/nodes/pve/tasks":
            return [_task()]
        raise RuntimeError("test API exception")
    # Real pvesh errors are SubprocessError; API failures must never become OK guests.
    def api_pve(argv):
        if argv[2].endswith("/log"):
            raise FileNotFoundError()
        return api(argv)
    run = BackupReader("pve", api_pve).read(10)["runs"][0]
    assert run["status"] == "success"  # task itself authoritatively returned OK
    assert not run["log_available"]
    assert run["guests"] == []


def test_history_number_persists_and_validates(tmp_path):
    monitor = _monitor(tmp_path)
    assert monitor.limit == 10
    for value in (0, 51, -1, True, 5.5):
        assert not monitor.set_limit(value)
    assert monitor.set_limit(50)
    assert _monitor(tmp_path).limit == 50


def test_first_scan_does_not_replay_old_events_and_transitions_dedup(tmp_path):
    monitor = _monitor(tmp_path)
    started = int(time.time()) - 20
    first = {"coverage": "available", "runs": [build_run(
        _task(upid="past", status="OK", started=started),
        parse_log(_lines(), {}))]}
    monitor.process(first)
    assert monitor.outbox.pending() == ()
    monitor.process({"coverage": "available", "runs": [{
        **first["runs"][0], "upid": "next", "status": "running", "ended_at": None,
    }]})
    assert monitor.outbox.pending() == ()
    completed = {**first["runs"][0], "upid": "next", "status": "failed"}
    monitor.process({"coverage": "available", "runs": [completed]})
    monitor.process({"coverage": "available", "runs": [completed]})
    pending = monitor.outbox.pending()
    assert len(pending) == 1
    assert pending[0].payload["event_type"] == "backup_job_failed"
    assert not pending[0].payload.get("message")
    reloaded = _monitor(tmp_path)
    assert len(reloaded.outbox.pending()) == 1
    delivered = []
    reloaded.flush_events(lambda payload: delivered.append(payload) or True)
    assert len(delivered) == 1
    assert _monitor(tmp_path).outbox.pending() == ()


def test_entity_attributes_stay_below_ha_limit_at_50_runs(tmp_path):
    monitor = _monitor(tmp_path)
    giant = [
        {"id": str(i), "kind": "VM", "status": "success",
         "name": "Guest-" + "x" * 40, "size_gib": 10.0, "size_kind": "archive"}
        for i in range(30)
    ]
    runs = [{
        "upid": "u-" + str(i), "started_at": "2026-11-22T03:00:00+00:00",
        "label": "Nightly job " + str(i), "status": "success",
        "duration_seconds": 30, "size_gib": 300.0, "size_kind": "archive",
        "guests": giant,
    } for i in range(50)]
    monitor.snapshot = {"coverage": "available", "runs": runs}
    view = monitor.view()
    assert len(view["runs"]) == 50
    assert view["details_limited"]
    assert len(json.dumps(view, ensure_ascii=False).encode()) < 15000


def test_backup_discovery_contains_stable_sensor_number_and_event():
    ident = HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a", hostname="pve", node_name="PVE")
    mqtt = MqttConfig(
        host="mqtt", port=1883, username="", password="",
        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
        discovery_prefix="homeassistant", keepalive_seconds=60)
    topics = build_topics(mqtt, ident)
    d = backup_components(topics)
    assert d["backup_history"]["unique_id"] == "dh_pve_agent_backup_history_id"
    number = d["backup_history_limit"]
    assert number["default_entity_id"] == "number.dh_pve_agent_backup_history_limit"
    assert (number["min"], number["max"], number["step"]) == (1, 50, 1)
    assert d["backup_event"]["event_types"] == [
        "backup_job_failed", "backup_job_completed"]
    events = MqttEvents(topics, RuntimeSettings())
    topic = f"{topics.base}/backup/history_limit/set"
    assert events.handle_message(topic, b"7.0")
    assert events.backup_limit_updates.get_nowait() == 7
    assert not events.handle_message(topic, b"51")
    assert not events.handle_message(topic, b"0")


def test_dashboard_uses_collapsible_tree_and_number():
    from pathlib import Path
    import yaml

    raw = (Path(__file__).resolve().parents[1] / "dashboards" / "ru" /
           "10_pve_proxmox.yaml").read_text()
    assert "<details" in raw
    assert "state !== 'success'" in raw
    assert "number.dh_pve_agent_backup_history_limit" in raw
    yaml.safe_load(raw)


def test_active_task_is_included_from_source_all():
    task = _task(upid="UPID:pve:0:0:0:vzdump::root@pam:", status="RUNNING")
    def api(argv):
        if argv[2] == "/cluster/backup":
            return []
        if argv[2] == "/nodes/pve/tasks":
            assert "--source" in argv and argv[argv.index("--source")+1] == "all"
            return [task]
        if argv[2].endswith("/log"):
            return [{"t": "INFO: Starting Backup of VM 2222 (qemu)"}]
        raise AssertionError(argv)
    run = BackupReader("pve", api).read(10)["runs"][0]
    assert run["status"] == "running"
    assert run["guests"][0]["status"] == "running"


def test_missing_endtime_does_not_imply_running():
    row = _task(status="")
    row.pop("endtime")
    assert build_run(row, parse_log([], {}))["status"] == "unknown"
