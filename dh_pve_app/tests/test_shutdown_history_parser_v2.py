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
