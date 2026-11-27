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


def test_real_pve_84_failed_group_99100_with_nine_successful_guests():
    # Confirmed 2026-11-22 03:00 and 02:42 on PVE 8.4.21.
    # Minimal task-log fixture retains all guest boundaries and exact failure.
    log = [
        "INFO: starting new backup job: vzdump 1237 10004 10001 1011 99100 "
        "99134 777 1221 7000 2222 --mode snapshot --storage pbs-serzhan",
        "INFO: Starting Backup of VM 777 (qemu)",
        "INFO: VM Name: digitalhouses.vip",
        "INFO: transferred 32.00 GiB in 19 seconds (1.7 GiB/s)",
        "INFO: Finished Backup of VM 777 (00:00:21)",
        "INFO: Starting Backup of VM 1011 (lxc)",
        "INFO: root.pxar: had to backup 20.744 MiB of 2.452 GiB "
        "(compressed 4.843 MiB) in 10.51 s",
        "INFO: Finished Backup of VM 1011 (00:00:12)",
        "INFO: Starting Backup of VM 1221 (lxc)",
        "INFO: root.pxar: had to backup 0 B of 1.301 GiB (compressed 0 B)",
        "INFO: Finished Backup of VM 1221 (00:00:15)",
        "INFO: Starting Backup of VM 1237 (lxc)",
        "INFO: root.pxar: had to backup 8.764 MiB of 1.945 GiB (compressed 2.85 MiB)",
        "INFO: Finished Backup of VM 1237 (00:00:17)",
        "INFO: Starting Backup of VM 2222 (qemu)",
        "INFO: transferred 1.22 GiB in 4 seconds (312.0 MiB/s)",
        "INFO: Finished Backup of VM 2222 (00:00:17)",
        "INFO: Starting Backup of VM 7000 (lxc)",
        "INFO: root.pxar: had to backup 0 B of 1.636 GiB (compressed 0 B)",
        "INFO: Finished Backup of VM 7000 (00:00:07)",
        "INFO: Starting Backup of VM 10001 (lxc)",
        "INFO: root.pxar: had to backup 7.94 MiB of 3.274 GiB (compressed 2.325 MiB)",
        "INFO: Finished Backup of VM 10001 (00:00:15)",
        "INFO: Starting Backup of VM 10004 (lxc)",
        "INFO: root.pxar: had to backup 0 B of 1.509 GiB (compressed 0 B)",
        "INFO: Finished Backup of VM 10004 (00:00:09)",
        "INFO: Starting Backup of VM 99100 (qemu)",
        "ERROR: Backup of VM 99100 failed - no such logical volume pve/vm-100-disk-1",
        "INFO: Failed at 2026-11-22 03:01:53",
        "INFO: Starting Backup of VM 99134 (qemu)",
        "INFO: transferred 32.00 GiB in 22 seconds (1.5 GiB/s)",
        "INFO: Finished Backup of VM 99134 (00:00:24)",
        "INFO: Backup job finished with errors",
        "TASK ERROR: job errors",
    ]
    run = build_run(_task(status="job errors"), parse_log(log, {
        "dh-backup-critical-daily": "Configured daily job",
    }))
    assert run["status"] == "failed"
    assert run["label"] == "vzdump · pbs-serzhan"
    assert run["job_id"] is None
    guests = {guest["id"]: guest for guest in run["guests"]}
    assert len(guests) == 10
    assert sum(g["status"] == "success" for g in guests.values()) == 9
    assert sum(g["status"] == "failed" for g in guests.values()) == 1
    assert guests["99100"]["kind"] == "VM"
    assert guests["99100"]["error"] == "no such logical volume pve/vm-100-disk-1"
    assert guests["1221"]["size_gib"] == 1.3
    assert guests["1221"]["size_kind"] == "processed"
    assert run["size_gib"] is None  # Do not report a complete total for a failed job.


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
        if argv[2] == "/cluster/resources":
            return []
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
        if argv[2] == "/cluster/resources":
            return []
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


def test_backup_failure_event_includes_verified_guest_error_and_name(tmp_path):
    monitor = _monitor(tmp_path)
    upid = "UPID:pve:002324B3:1019E2E7:6B021460:vzdump::root@pam:"
    running = build_run(
        _task(upid=upid, status="RUNNING"),
        parse_log(["INFO: Starting Backup of VM 99100 (qemu)"], {}),
    )
    monitor.process({"coverage": "available", "runs": [running]})
    assert monitor.outbox.pending() == ()

    parsed = parse_log([
        "INFO: starting new backup job: vzdump 99100 --storage pbs-serzhan",
        "INFO: Starting Backup of VM 99100 (qemu)",
        "INFO: VM Name: ha-prod",
        "ERROR: Backup of VM 99100 failed - no such logical volume pve/vm-100-disk-1",
    ], {})
    failed = build_run(_task(upid=upid, status="job errors"), parsed)
    monitor.process({"coverage": "available", "runs": [failed]})
    monitor.process({"coverage": "available", "runs": [failed]})
    pending = monitor.outbox.pending()
    assert len(pending) == 1
    payload = pending[0].payload
    assert payload["event_type"] == "backup_job_failed"
    assert payload["job_name"] == "vzdump · pbs-serzhan"
    assert payload["error"] == "job errors"
    assert payload["guests"] == [{
        "id": "99100", "kind": "VM", "status": "failed",
        "name": "ha-prod", "error": "no such logical volume pve/vm-100-disk-1",
    }]


def test_backup_failure_notification_is_portable_and_admin_delivery_is_optional():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    portable = (root / "packages/locales/ru/"
                "dh_pve_agent_notification_local_package.yaml").read_text()
    admin = (root / "examples/packages/locales/ru/"
             "dh_pve_agent_backup_write2admins.yaml").read_text()

    assert "id: dh_pve_agent_backup_failed_notification" in portable
    assert "entity_id: event.dh_pve_agent_backup" in portable
    assert "backup_job_failed" in portable
    assert "action: persistent_notification.create" in portable
    assert "script.write2admins" not in portable
    assert "id: dh_pve_agent_backup_failed_write2admins" in admin
    assert "action: script.write2admins" in admin
    assert "action: persistent_notification.create" not in admin
    assert "g.error" in portable and "g.error" in admin
    assert "a.error" in portable and "a.error" in admin
    assert "ns.missing" in portable and "ns.missing" in admin
    assert "ns.unknown" in portable and "ns.unknown" in admin
    assert "ns.skipped" in portable and "ns.skipped" in admin
    # Both packages use one backup-failure event only; no success alert spam.
    assert portable.count("- backup_job_failed") == 1
    assert admin.count("- backup_job_failed") == 1


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

    raw = (Path(__file__).resolve().parents[1] / "dashboards" / "ru" /
           "10_pve_proxmox.yaml").read_text()
    assert "<details" in raw
    assert "state !== 'success'" in raw
    assert "number.dh_pve_agent_backup_history_limit" in raw
    assert "sensor.dh_pve_agent_backup_history" in raw
    # The repository contract validator already parses canonical dashboard YAML.
    # Avoid adding PyYAML to the agent runtime just for this view smoke test.


def test_active_task_is_included_from_source_all():
    task = _task(upid="UPID:pve:0:0:0:vzdump::root@pam:", status="RUNNING")
    def api(argv):
        if argv[2] == "/cluster/resources":
            return []
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


def test_explicit_skip_and_duration():
    rows = parse_log(["INFO: Starting Backup of VM 100 (qemu)",
                      "INFO: Finished Backup of VM 100 (00:01:02)",
                      "WARNING: skipping Backup of VM 101",
                      "WARNING: Backup of VM 102 skipped"], {})["guests"]
    assert rows[0]["duration_seconds"] == 62
    assert [r["status"] for r in rows] == ["success", "skipped", "skipped"]


def test_single_reader_reports_configured_coverage_without_extra_task_reads():
    calls = []
    def api(argv):
        path = argv[2]
        calls.append(path)
        if path == "/cluster/backup":
            return [{"id":"daily","all":1,"exclude":"103","enabled":1},
                    {"id":"off","vmid":"103","enabled":0}]
        if path == "/cluster/resources":
            return [{"node":"pve","vmid":v,"type":"qemu"} for v in [101,102,103]]
        if path == "/nodes/pve/tasks":
            return []
        raise AssertionError(path)
    snapshot = BackupReader("pve", api).read(10)
    assert snapshot["job_inventory"]["counts"] == {"covered":2,"uncovered":0,"excluded":1,"unknown":0}
    assert calls.count("/cluster/backup") == calls.count("/nodes/pve/tasks") == 1


def test_coverage_unknown_when_selector_unavailable():
    from app.backup_coverage import collect_inventory
    inventory = collect_inventory("pve", [{"id":"daily","pool":"missing"}],
                                  lambda path,*args: [{"node":"pve","vmid":100}] if path == "/cluster/resources" else {})
    assert inventory["status"] == "unknown"
    assert inventory["guests"][0]["status"] == "unknown"


def test_coverage_view_does_not_present_zero_counts_for_legacy_agents():
    from pathlib import Path
    raw = (Path(__file__).resolve().parents[1] / "dashboards" / "ru" /
           "10_pve_proxmox.yaml").read_text()
    card = raw.split("title: PVE · Покрытие заданиями", 1)[1].split("grid_options:", 1)[0]
    assert "c is not mapping" in card
    assert all(f"'{key}' in c" in card for key in ("covered", "uncovered", "excluded", "unknown"))
    assert card.index("Инвентаризация недоступна") < card.index("В заданиях:")
    assert "Покрытие определено не полностью" in card
