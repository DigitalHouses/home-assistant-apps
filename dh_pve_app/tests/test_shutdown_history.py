from app.shutdown_history import (
    ShutdownHistoryTracker,
    evaluate_shutdown_readiness,
    parse_guest_shutdown_journal,
)
from app.state_store import StateStore
from app.ups_nut import parse_upsc_output


JOURNAL = """\
2026-09-13T23:05:03.007435+05:00 pve pve-guests[1]: Stopping VM 110 (timeout = 60 seconds)
2026-09-13T23:06:03.178191+05:00 pve pvedaemon[1]: VM 110 qmp guest-shutdown got timeout
2026-09-13T23:06:05.038134+05:00 pve pvedaemon[1]: end task UPID:pve:0001:0001:0001:0001:qmshutdown:110:root@pam: OK
2026-09-13T23:07:09.080669+05:00 pve pve-guests[1]: Stopping VM 700 (timeout = 100 seconds)
2026-09-13T23:07:22.098022+05:00 pve pvedaemon[1]: end task UPID:pve:0002:0002:0002:0002:qmshutdown:700:root@pam: OK
2026-09-13T23:07:23.098426+05:00 pve pve-guests[1]: all VMs and CTs stopped
2026-09-13T23:09:09.088265+05:00 pve systemd[1]: Reached target shutdown.target - System Shutdown.
"""


def test_parse_guest_shutdown_journal_captures_duration_timeout_and_total():
    parsed = parse_guest_shutdown_journal(JOURNAL)

    haos = parsed["guests"]["vm"]["110"]
    assert haos["timeout_seconds"] == 60
    assert haos["duration_seconds"] == 62
    assert haos["result"] == "timeout"
    assert haos["forced"] is True
    assert haos["timeout_ratio"] > 1.0

    truenas = parsed["guests"]["vm"]["700"]
    assert truenas["timeout_seconds"] == 100
    assert truenas["duration_seconds"] == 13
    assert truenas["result"] == "clean"
    assert truenas["forced"] is False

    assert parsed["all_guests_stopped_at"] == "2026-09-13T23:07:23.098426+05:00"
    assert parsed["guest_shutdown_total_seconds"] == 140
    assert parsed["clean_shutdown"] is True


def test_tracker_classifies_previous_boot_as_ups_power_and_keeps_history(tmp_path):
    store = StateStore(tmp_path / "shutdown.json")
    store.save(
        {
            "current_boot": {
                "boot_id": "old-boot",
                "boot_at": "2026-09-13T01:00:00+05:00",
                "outage_started_at": "2026-09-13T22:33:12+05:00",
                "fsd_at": "2026-09-13T23:03:34+05:00",
                "fsd_reason": "on_battery_fsd",
                "ups_status_at_fsd": "OB FSD",
            },
            "history": [],
        }
    )
    tracker = ShutdownHistoryTracker(
        state_store=store,
        boot_id_reader=lambda: "new-boot",
        boot_time_reader=lambda: "2026-09-13T23:28:14+05:00",
        previous_boot_journal_reader=lambda: JOURNAL,
    )

    payload = tracker.startup()

    previous = payload["previous_shutdown"]
    assert previous["shutdown_class"] == "ups_power"
    assert previous["shutdown_reason"] == "on_battery_fsd"
    assert previous["outage_started_at"] == "2026-09-13T22:33:12+05:00"
    assert previous["fsd_at"] == "2026-09-13T23:03:34+05:00"
    assert previous["guests"]["vm"]["110"]["result"] == "timeout"
    assert len(payload["history"]) == 1
    assert payload["current_boot"]["boot_id"] == "new-boot"

    tracker.startup()
    assert len(tracker.payload()["history"]) == 1


def test_tracker_marks_unclean_boot_without_clean_shutdown_marker(tmp_path):
    store = StateStore(tmp_path / "shutdown.json")
    store.save(
        {
            "current_boot": {
                "boot_id": "old-boot",
                "boot_at": "2026-09-13T01:00:00+05:00",
            },
            "history": [],
        }
    )
    tracker = ShutdownHistoryTracker(
        state_store=store,
        boot_id_reader=lambda: "new-boot",
        boot_time_reader=lambda: "2026-09-14T01:00:00+05:00",
        previous_boot_journal_reader=lambda: (
            "2026-09-13T23:59:59.000000+05:00 pve kernel: last message before reset\n"
        ),
    )

    previous = tracker.startup()["previous_shutdown"]

    assert previous["shutdown_class"] == "unclean"
    assert previous["shutdown_reason"] == "no_clean_shutdown"


def test_tracker_records_on_battery_and_fsd_facts(tmp_path):
    clock = {"iso": "2026-09-14T10:00:00+05:00"}
    tracker = ShutdownHistoryTracker(
        state_store=StateStore(tmp_path / "shutdown.json"),
        boot_id_reader=lambda: "boot-a",
        boot_time_reader=lambda: "2026-09-14T09:00:00+05:00",
        previous_boot_journal_reader=lambda: "",
        now_iso=lambda: clock["iso"],
    )
    tracker.startup()

    tracker.observe_ups(parse_upsc_output("ups.status: OB DISCHRG\nbattery.charge: 80\n"))
    clock["iso"] = "2026-09-14T10:30:00+05:00"
    tracker.observe_ups(
        parse_upsc_output(
            "ups.status: OB LB FSD\nbattery.charge: 12\nbattery.runtime: 580\nups.load: 20\n"
        )
    )

    current = tracker.payload()["current_boot"]
    assert current["outage_started_at"] == "2026-09-14T10:00:00+05:00"
    assert current["fsd_at"] == "2026-09-14T10:30:00+05:00"
    assert current["fsd_reason"] == "low_battery_fsd"
    assert current["battery_charge_at_fsd"] == 12.0
    assert current["battery_runtime_at_fsd"] == 580.0
    assert current["ups_load_at_fsd"] == 20.0


def test_readiness_skips_without_ups_and_warns_on_bad_guest():
    assert evaluate_shutdown_readiness(
        ups_present=False,
        guest_shutdown_budget_seconds=None,
        previous_shutdown=None,
    )["status"] == "skip"

    warning = evaluate_shutdown_readiness(
        ups_present=True,
        guest_shutdown_budget_seconds=420,
        previous_shutdown={
            "guests": {
                "vm": {
                    "110": {
                        "duration_seconds": 62,
                        "timeout_seconds": 60,
                        "timeout_ratio": 62 / 60,
                        "result": "timeout",
                        "forced": True,
                    }
                },
                "lxc": {},
            }
        },
    )
    assert warning["status"] == "warning"
    assert "vm:110:timeout" in warning["issues"]
    assert warning["guest_shutdown_budget_seconds"] == 420


def test_readiness_ok_for_clean_fast_guests():
    result = evaluate_shutdown_readiness(
        ups_present=True,
        guest_shutdown_budget_seconds=420,
        previous_shutdown={
            "guests": {
                "vm": {
                    "700": {
                        "duration_seconds": 13,
                        "timeout_seconds": 100,
                        "timeout_ratio": 0.13,
                        "result": "clean",
                        "forced": False,
                    }
                },
                "lxc": {},
            }
        },
    )

    assert result["status"] == "ok"
    assert result["issues"] == []
