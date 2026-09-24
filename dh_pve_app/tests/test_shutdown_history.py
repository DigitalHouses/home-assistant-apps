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
    assert haos["forced"] is False
    assert haos["timeout_ratio"] > 1.0

    truenas = parsed["guests"]["vm"]["700"]
    assert truenas["timeout_seconds"] == 100
    assert truenas["duration_seconds"] == 13
    assert truenas["result"] == "clean"
    assert truenas["forced"] is False

    assert parsed["all_guests_stopped_at"] == "2026-09-13T23:07:23.098426+05:00"
    assert parsed["guest_shutdown_total_seconds"] == 140
    assert parsed["clean_shutdown"] is True
    assert parsed["shutdown_at"] == "2026-09-13T23:09:09.088265+05:00"
    assert parsed["last_journal_at"] == "2026-09-13T23:09:09.088265+05:00"


def test_parse_real_proxmox_sigterm_marks_single_active_vm_forced():
    parsed = parse_guest_shutdown_journal(
        "2026-09-13T23:05:03.000000+05:00 pve pve-guests[1]: Stopping VM 110 (timeout = 60 seconds)\n"
        "2026-09-13T23:06:03.000000+05:00 pve pvedaemon[2]: VM quit/powerdown failed - terminating now with SIGTERM\n"
        "2026-09-13T23:06:05.000000+05:00 pve pvedaemon[1]: end task UPID:pve:0001:0001:0001:0001:qmshutdown:110:root@pam: OK\n"
    )

    guest = parsed["guests"]["vm"]["110"]
    assert guest["duration_seconds"] == 62
    assert guest["result"] == "forced"
    assert guest["forced"] is True


def test_parse_real_proxmox_end_task_timeout_is_not_clean():
    parsed = parse_guest_shutdown_journal(
        "2026-09-13T23:05:03.000000+05:00 pve pve-guests[1]: Stopping VM 110 (timeout = 60 seconds)\n"
        "2026-09-13T23:06:03.000000+05:00 pve pvedaemon[1]: end task UPID:pve:0001:0001:0001:0001:qmshutdown:110:root@pam: VM quit/powerdown failed - got timeout\n"
    )

    guest = parsed["guests"]["vm"]["110"]
    assert guest["duration_seconds"] == 60
    assert guest["result"] == "timeout"
    assert guest["forced"] is False


def test_parse_unclean_journal_does_not_invent_shutdown_time():
    parsed = parse_guest_shutdown_journal(
        "2026-09-13T23:59:59.000000+05:00 pve kernel: last message before reset\n"
    )

    assert parsed["clean_shutdown"] is False
    assert parsed["shutdown_at"] is None
    assert parsed["last_journal_at"] == "2026-09-13T23:59:59+05:00"


def test_parse_empty_journal_has_unknown_shutdown_result():
    parsed = parse_guest_shutdown_journal("")

    assert parsed["clean_shutdown"] is None
    assert parsed["shutdown_at"] is None
    assert parsed["last_journal_at"] is None


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
    assert previous["shutdown_clean"] is True
    assert previous["outage_started_at"] == "2026-09-13T22:33:12+05:00"
    assert previous["fsd_at"] == "2026-09-13T23:03:34+05:00"
    assert previous["outage_to_fsd_seconds"] == 1822
    assert previous["fsd_to_all_guests_stopped_seconds"] == 229
    assert previous["fsd_to_shutdown_seconds"] == 335
    assert previous["all_guests_stopped_to_shutdown_seconds"] == 106
    assert previous["outage_to_shutdown_seconds"] == 2157
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
    assert previous["shutdown_reason"] == "unknown"
    assert previous["shutdown_clean"] is False
    assert previous["shutdown_at"] is None
    assert previous["last_journal_at"] == "2026-09-13T23:59:59+05:00"
    assert previous["downtime_seconds"] is None


def test_tracker_marks_missing_journal_evidence_unknown(tmp_path):
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
        previous_boot_journal_reader=lambda: "",
    )

    previous = tracker.startup()["previous_shutdown"]

    assert previous["shutdown_class"] == "unknown"
    assert previous["shutdown_reason"] == "unknown"
    assert previous["shutdown_clean"] is None
    assert previous["shutdown_at"] is None


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


def test_readiness_warns_if_ups_power_shutdown_did_not_finish_cleanly():
    warning = evaluate_shutdown_readiness(
        ups_present=True,
        guest_shutdown_budget_seconds=420,
        previous_shutdown={
            "shutdown_class": "ups_power",
            "shutdown_clean": False,
            "guests": {"vm": {}, "lxc": {}},
        },
    )

    assert warning["status"] == "warning"
    assert "previous_host_shutdown_unclean" in warning["issues"]


def test_readiness_warns_if_ups_power_shutdown_result_is_unknown():
    warning = evaluate_shutdown_readiness(
        ups_present=True,
        guest_shutdown_budget_seconds=420,
        previous_shutdown={
            "shutdown_class": "ups_power",
            "shutdown_clean": None,
            "guests": {"vm": {}, "lxc": {}},
        },
    )

    assert warning["status"] == "warning"
    assert "previous_host_shutdown_unknown" in warning["issues"]


def test_readiness_ok_for_clean_fast_guests():
    result = evaluate_shutdown_readiness(
        ups_present=True,
        guest_shutdown_budget_seconds=420,
        previous_shutdown={
            "shutdown_class": "normal",
            "shutdown_clean": True,
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
            },
        },
    )

    assert result["status"] == "ok"
    assert result["issues"] == []

def test_incident_parser_discards_stale_guest_completion_before_new_shutdown_start():
    parsed = parse_guest_shutdown_journal(
        "2026-09-21T19:36:32.560792+05:00 pve pve-guests[1]: "
        "end task UPID:pve:1:2:3:4:qmshutdown:110:root@pam:\n"
        "2026-09-24T04:45:40.871419+05:00 pve pve-guests[2]: "
        "Stopping VM 110 (timeout = 125 seconds)\n"
    )

    guest = parsed["guests"]["vm"]["110"]
    assert guest["started_at"] == "2026-09-24T04:45:40.871419+05:00"
    assert guest["finished_at"] is None
    assert guest["duration_seconds"] is None
    assert guest["timeout_ratio"] is None
    assert guest["result"] == "unknown"


def test_powering_down_message_is_not_final_clean_shutdown_evidence():
    parsed = parse_guest_shutdown_journal(
        "2026-09-24T04:44:34.000000+05:00 pve systemd-logind[1]: "
        "System is powering down.\n"
    )

    assert parsed["clean_shutdown"] is False
    assert parsed["shutdown_at"] is None

def test_shutdown_request_boundary_discards_earlier_same_boot_guest_operations():
    parsed = parse_guest_shutdown_journal(
        "2026-09-23T10:54:30.000000+05:00 pve pve-guests[1]: "
        "Stopping CT 100 (timeout = 30 seconds)\n"
        "2026-09-23T10:55:02.000000+05:00 pve pve-guests[1]: "
        "end task UPID:pve:1:2:3:4:vzshutdown:100:root@pam:\n"
        "2026-09-24T04:44:34.000000+05:00 pve systemd-logind[2]: "
        "The system will power off now!\n"
        "2026-09-24T04:44:34.100000+05:00 pve systemd-logind[2]: "
        "System is powering down.\n"
        "2026-09-24T04:45:40.000000+05:00 pve pve-guests[3]: "
        "Stopping VM 110 (timeout = 125 seconds)\n"
    )

    assert "100" not in parsed["guests"]["lxc"]
    assert parsed["guests"]["vm"]["110"]["result"] == "unknown"
    assert parsed["guests"]["vm"]["110"]["finished_at"] is None

def test_shutdown_scope_resets_earlier_clean_marker_and_incomplete_total():
    parsed = parse_guest_shutdown_journal(
        "2026-09-23T18:18:13.252074+05:00 pve some-service[1]: "
        "referenced systemd-shutdown helper during normal runtime\n"
        "2026-09-24T04:44:34.000000+05:00 pve systemd-logind[2]: "
        "The system will power off now!\n"
        "2026-09-24T04:44:38.720856+05:00 pve pve-guests[3]: "
        "Stopping VM 501 (timeout = 30 seconds)\n"
        "2026-09-24T04:45:06.801121+05:00 pve pve-guests[3]: "
        "end task UPID:pve:1:2:3:4:qmshutdown:501:root@pam:\n"
        "2026-09-24T04:45:40.871419+05:00 pve pve-guests[3]: "
        "Stopping VM 110 (timeout = 125 seconds)\n"
    )

    assert parsed["clean_shutdown"] is False
    assert parsed["shutdown_at"] is None
    assert parsed["guest_shutdown_total_seconds"] is None
    assert parsed["guests"]["vm"]["501"]["result"] == "clean"
    assert parsed["guests"]["vm"]["110"]["result"] == "unknown"
    assert parsed["guests"]["vm"]["110"]["finished_at"] is None

