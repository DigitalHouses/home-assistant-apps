from app.shutdown_history import ShutdownHistoryTracker, parse_guest_shutdown_journal
from app.state_store import StateStore


REAL_WINDOW = """\
2026-09-15T07:28:06.000000+05:00 pve pvesh[1]: Stopping VM 501 (timeout = 30 seconds)
2026-09-15T07:28:06.000000+05:00 pve pve-guests[2]: shutdown VM 501: task
2026-09-15T07:28:11.000000+05:00 pve qm[3]: VM 501 qmp command failed - VM 501 qmp command 'guest-ping' failed - got timeout
2026-09-15T07:28:27.000000+05:00 pve qmeventd[4]: Finished cleanup for 501
2026-09-15T07:28:28.000000+05:00 pve pve-guests[2]: end task UPID:pve:1:2:3:4:qmshutdown:501:root@pam:
2026-09-15T07:30:05.000000+05:00 pve pvesh[1]: Stopping VM 700 (timeout = 100 seconds)
2026-09-15T07:30:17.000000+05:00 pve qmeventd[5]: Finished cleanup for 700
2026-09-15T07:30:18.000000+05:00 pve pve-guests[2]: end task UPID:pve:5:6:7:8:qmshutdown:700:root@pam:
2026-09-15T07:31:56.000000+05:00 pve systemd[1]: Reached target shutdown.target - System Shutdown.
"""


def test_guest_ping_timeout_does_not_mark_shutdown_timeout():
    parsed = parse_guest_shutdown_journal(REAL_WINDOW)

    vm501 = parsed["guests"]["vm"]["501"]
    assert vm501["duration_seconds"] == 22
    assert vm501["timeout_seconds"] == 30
    assert vm501["result"] == "clean"
    assert vm501["forced"] is False

    vm700 = parsed["guests"]["vm"]["700"]
    assert vm700["duration_seconds"] == 13
    assert vm700["timeout_seconds"] == 100
    assert vm700["result"] == "clean"
    assert vm700["forced"] is False


def test_same_boot_startup_reconciles_legacy_previous_shutdown_parser_result(tmp_path):
    store = StateStore(tmp_path / "shutdown_history.json")
    stale_previous = {
        "boot_id": "old-boot",
        "boot_at": "2026-09-13T23:28:11+05:00",
        "shutdown_at": "2026-09-15T07:31:56+05:00",
        "shutdown_class": "ups_power",
        "shutdown_reason": "low_battery_fsd",
        "shutdown_clean": True,
        "outage_started_at": "2026-09-15T07:02:19+05:00",
        "fsd_at": "2026-09-15T07:27:51+05:00",
        "battery_charge_at_fsd": 21.0,
        "battery_runtime_at_fsd": 1257.0,
        "guests": {
            "vm": {
                "501": {"result": "timeout", "forced": True},
                "700": {"result": "timeout", "forced": True},
            },
            "lxc": {},
        },
    }
    store.save(
        {
            "current_boot": {
                "boot_id": "current-boot",
                "boot_at": "2026-09-15T07:34:19+05:00",
            },
            "previous_shutdown": stale_previous,
            "history": [stale_previous],
        }
    )

    tracker = ShutdownHistoryTracker(
        state_store=store,
        boot_id_reader=lambda: "current-boot",
        boot_time_reader=lambda: "2026-09-15T07:34:19+05:00",
        previous_boot_journal_reader=lambda: REAL_WINDOW,
    )

    payload = tracker.startup()
    previous = payload["previous_shutdown"]

    assert previous["shutdown_reason"] == "low_battery_fsd"
    assert previous["battery_charge_at_fsd"] == 21.0
    assert previous["battery_runtime_at_fsd"] == 1257.0
    assert previous["guests"]["vm"]["501"]["result"] == "clean"
    assert previous["guests"]["vm"]["700"]["result"] == "clean"
    assert previous["history_parser_version"] >= 2
    assert payload["history"][-1]["history_parser_version"] >= 2

def test_v5_reconciliation_preserves_v4_shutdown_scope_fix(tmp_path):
    store = StateStore(tmp_path / "shutdown_history.json")
    stale_previous = {
        "history_parser_version": 3,
        "boot_id": "old-boot",
        "boot_at": "2026-09-23T13:27:59+05:00",
        "shutdown_at": "2026-09-24T04:44:34+05:00",
        "last_journal_at": "2026-09-24T04:45:40+05:00",
        "shutdown_class": "ups_power",
        "shutdown_reason": "on_battery_fsd",
        "shutdown_clean": True,
        "outage_started_at": "2026-09-24T04:19:41+05:00",
        "fsd_at": "2026-09-24T04:44:29+05:00",
        "battery_charge_at_fsd": 30.0,
        "battery_runtime_at_fsd": 2520.0,
        "ups_load_at_fsd": 5.0,
        "all_guests_stopped_at": "2026-09-21T19:36:32+05:00",
        "guest_shutdown_total_seconds": 0,
        "guests": {
            "vm": {
                "110": {
                    "started_at": "2026-09-24T04:45:40+05:00",
                    "finished_at": "2026-09-21T19:36:32+05:00",
                    "duration_seconds": 0,
                    "result": "clean",
                    "forced": False,
                }
            },
            "lxc": {
                "100": {
                    "started_at": "2026-09-23T10:54:30+05:00",
                    "finished_at": "2026-09-23T10:55:02+05:00",
                    "duration_seconds": 32,
                    "result": "clean",
                    "forced": False,
                }
            },
        },
    }
    store.save(
        {
            "current_boot": {
                "boot_id": "current-boot",
                "boot_at": "2026-09-24T05:20:20+05:00",
            },
            "previous_shutdown": stale_previous,
            "history": [stale_previous],
        }
    )

    journal = (
        "2026-09-23T18:18:13.252074+05:00 pve some-service[9]: "
        "referenced systemd-shutdown helper during normal runtime\n"
        "2026-09-23T10:54:30.000000+05:00 pve pve-guests[1]: "
        "Stopping CT 100 (timeout = 30 seconds)\n"
        "2026-09-23T10:55:02.000000+05:00 pve pve-guests[1]: "
        "end task UPID:pve:1:2:3:4:vzshutdown:100:root@pam:\n"
        "2026-09-24T04:44:34.000000+05:00 pve systemd-logind[2]: "
        "The system will power off now!\n"
        "2026-09-24T04:44:34.100000+05:00 pve systemd-logind[2]: "
        "System is powering down.\n"
        "2026-09-24T04:45:40.871419+05:00 pve pve-guests[3]: "
        "Stopping VM 110 (timeout = 125 seconds)\n"
    )

    tracker = ShutdownHistoryTracker(
        state_store=store,
        boot_id_reader=lambda: "current-boot",
        boot_time_reader=lambda: "2026-09-24T05:20:20+05:00",
        previous_boot_journal_reader=lambda: journal,
    )

    previous = tracker.startup()["previous_shutdown"]

    assert previous["history_parser_version"] == 5
    assert previous["shutdown_class"] == "ups_power"
    assert previous["shutdown_reason"] == "on_battery_fsd"
    assert previous["shutdown_clean"] is False
    assert previous["shutdown_at"] is None
    assert previous["all_guests_stopped_at"] is None
    assert previous["guest_shutdown_total_seconds"] is None
    assert previous["fsd_to_shutdown_seconds"] is None
    assert previous["guests"]["lxc"] == {}
    assert set(previous["guests"]["vm"]) == {"110"}
    vm110 = previous["guests"]["vm"]["110"]
    assert vm110["started_at"] == "2026-09-24T04:45:40.871419+05:00"
    assert vm110["finished_at"] is None
    assert vm110["duration_seconds"] is None
    assert vm110["result"] == "unknown"



def test_manual_pct_shutdown_task_upid_records_duration_from_real_pve_journal():
    journal = """\
2026-09-26T01:10:32.607284+0500 pve pct[247662]: <root@pam> starting task UPID:pve:0003C76F:00F0CD27:6AB6D538:vzshutdown:333:root@pam:
2026-09-26T01:10:32.610709+0500 pve pct[247663]: shutdown CT 333: UPID:pve:0003C76F:00F0CD27:6AB6D538:vzshutdown:333:root@pam:
2026-09-26T01:10:44.543655+0500 pve pct[247662]: <root@pam> end task UPID:pve:0003C76F:00F0CD27:6AB6D538:vzshutdown:333:root@pam: OK
"""

    parsed = parse_guest_shutdown_journal(journal)
    item = parsed["guests"]["lxc"]["333"]

    assert item["started_at"] == "2026-09-26T01:10:32.607284+05:00"
    assert item["finished_at"] == "2026-09-26T01:10:44.543655+05:00"
    assert item["duration_seconds"] == 12
    assert item["timeout_seconds"] is None
    assert item["result"] == "clean"
    assert item["forced"] is False
