from app.shutdown_history import ShutdownHistoryTracker
from app.state_store import StateStore


def test_current_budget_fingerprint_is_carried_into_next_previous_shutdown(tmp_path):
    boot = {"id": "boot-a", "at": "2026-09-16T00:00:00+05:00"}
    journal = {
        "text": (
            "2026-09-16T01:00:00+05:00 Stopping VM 110 (timeout = 60 seconds)\n"
            "2026-09-16T01:00:30+05:00 end task UPID:x:qmshutdown:110: OK\n"
            "2026-09-16T01:00:31+05:00 all VMs and CTs stopped\n"
            "2026-09-16T01:00:45+05:00 Reached target shutdown.target\n"
        )
    }
    tracker = ShutdownHistoryTracker(
        state_store=StateStore(tmp_path / "shutdown.json"),
        boot_id_reader=lambda: boot["id"],
        boot_time_reader=lambda: boot["at"],
        previous_boot_journal_reader=lambda: journal["text"],
        now_iso=lambda: "2026-09-16T00:10:00+05:00",
    )
    tracker.startup()

    tracker.record_shutdown_budget_fingerprint("fingerprint-a")
    tracker.record_shutdown_budget_fingerprint("fingerprint-b")

    current = tracker.payload()["current_boot"]
    assert current["shutdown_budget_fingerprint"] == "fingerprint-b"

    boot["id"] = "boot-b"
    boot["at"] = "2026-09-16T01:02:00+05:00"
    tracker.startup()

    previous = tracker.payload()["previous_shutdown"]
    assert previous["shutdown_budget_fingerprint"] == "fingerprint-b"
    assert previous["shutdown_clean"] is True


def test_shutdown_plan_snapshot_is_carried_into_next_history_record(tmp_path):
    boot = {"id": "boot-a", "at": "2026-09-26T00:00:00+05:00"}
    journal = {
        "text": (
            "2026-09-26T01:00:00+05:00 Stopping VM 110 (timeout = 60 seconds)\n"
            "2026-09-26T01:00:20+05:00 end task UPID:x:qmshutdown:110: OK\n"
            "2026-09-26T01:00:21+05:00 all VMs and CTs stopped\n"
            "2026-09-26T01:00:40+05:00 Reached target shutdown.target\n"
        )
    }
    tracker = ShutdownHistoryTracker(
        state_store=StateStore(tmp_path / "shutdown.json"),
        boot_id_reader=lambda: boot["id"],
        boot_time_reader=lambda: boot["at"],
        previous_boot_journal_reader=lambda: journal["text"],
        now_iso=lambda: "2026-09-26T00:10:00+05:00",
    )
    tracker.startup()

    tracker.record_shutdown_plan(
        configuration_fingerprint="fingerprint-a",
        planned_shutdown_seconds=670,
        planned_guest_shutdown_seconds=460,
        planned_all_guest_shutdown_seconds=520,
        running_guests=["vm:110", "lxc:149"],
        shutdown_sequence=[["110"], ["149"]],
    )

    boot["id"] = "boot-b"
    boot["at"] = "2026-09-26T01:02:00+05:00"
    previous = tracker.startup()["previous_shutdown"]

    assert previous["shutdown_status"] == "correct"
    assert previous["planned_shutdown_seconds"] == 670
    assert previous["planned_guest_shutdown_seconds"] == 460
    assert previous["planned_all_guest_shutdown_seconds"] == 520
    assert previous["running_guests"] == ["vm:110", "lxc:149"]
    assert previous["shutdown_sequence"] == [["110"], ["149"]]


def test_manual_guest_shutdown_in_current_boot_updates_latest_guest_fact(tmp_path):
    current_journal = {
        "text": (
            "2026-09-26T00:20:00+05:00 pve pve-guests[1]: "
            "Stopping CT 149 (timeout = 60 seconds)\n"
            "2026-09-26T00:20:07+05:00 pve pve-guests[1]: "
            "end task UPID:pve:1:2:3:4:vzshutdown:149:root@pam:\n"
        )
    }
    tracker = ShutdownHistoryTracker(
        state_store=StateStore(tmp_path / "shutdown.json"),
        boot_id_reader=lambda: "boot-a",
        boot_time_reader=lambda: "2026-09-26T00:00:00+05:00",
        previous_boot_journal_reader=lambda: "",
        current_boot_journal_reader=lambda: current_journal["text"],
    )
    tracker.startup()

    assert tracker.refresh_current_guest_shutdowns() is True

    latest = tracker.payload()["guest_last_shutdowns"]["lxc"]["149"]
    assert latest["duration_seconds"] == 7
    assert latest["result"] == "clean"
    assert latest["source"] == "guest_shutdown"


def test_legacy_history_records_get_canonical_shutdown_status_in_payload(tmp_path):
    store = StateStore(tmp_path / "shutdown.json")
    store.save(
        {
            "current_boot": {
                "boot_id": "boot-current",
                "boot_at": "2026-09-26T02:00:00+05:00",
            },
            "previous_shutdown": {
                "boot_id": "boot-prev",
                "shutdown_class": "normal",
                "shutdown_clean": True,
            },
            "history": [
                {
                    "boot_id": "boot-good",
                    "shutdown_class": "normal",
                    "shutdown_clean": True,
                },
                {
                    "boot_id": "boot-bad",
                    "shutdown_class": "unclean",
                    "shutdown_clean": False,
                },
                {
                    "boot_id": "boot-unknown",
                    "shutdown_class": "unknown",
                    "shutdown_clean": None,
                },
            ],
        }
    )
    tracker = ShutdownHistoryTracker(
        state_store=store,
        boot_id_reader=lambda: "boot-current",
        boot_time_reader=lambda: "2026-09-26T02:00:00+05:00",
        previous_boot_journal_reader=lambda: "",
    )

    payload = tracker.payload()

    assert payload["previous_shutdown"]["shutdown_status"] == "correct"
    assert [item["shutdown_status"] for item in payload["history"]] == [
        "correct",
        "incorrect",
        "unknown",
    ]


def test_standalone_guest_shutdown_fact_is_enriched_once_from_guest_config(tmp_path):
    journal = {
        "text": (
            "2026-09-26T01:10:32.607284+0500 pve pct[247662]: "
            "<root@pam> starting task UPID:pve:1:2:3:4:vzshutdown:333:root@pam:\n"
            "2026-09-26T01:10:44.543655+0500 pve pct[247662]: "
            "<root@pam> end task UPID:pve:1:2:3:4:vzshutdown:333:root@pam: OK\n"
        )
    }
    tracker = ShutdownHistoryTracker(
        state_store=StateStore(tmp_path / "shutdown.json"),
        boot_id_reader=lambda: "boot-a",
        boot_time_reader=lambda: "2026-09-26T00:00:00+05:00",
        previous_boot_journal_reader=lambda: "",
        current_boot_journal_reader=lambda: journal["text"],
    )
    tracker.startup()
    assert tracker.refresh_current_guest_shutdowns() is True

    before = tracker.payload()["guest_last_shutdowns"]["lxc"]["333"]
    assert before["duration_seconds"] == 12
    assert before["timeout_seconds"] is None
    assert before["timeout_ratio"] is None
    assert before["assessment"] == "unknown"

    assert tracker.enrich_guest_last_shutdowns(
        {("lxc", "333"): 30}
    ) is True

    latest = tracker.payload()["guest_last_shutdowns"]["lxc"]["333"]
    assert latest["duration_seconds"] == 12
    assert latest["timeout_seconds"] == 30
    assert latest["timeout_ratio"] == 0.4
    assert latest["assessment"] == "ok"

    # Historical fact keeps the timeout that was attached to the shutdown.
    assert tracker.enrich_guest_last_shutdowns(
        {("lxc", "333"): 50}
    ) is False
    latest = tracker.payload()["guest_last_shutdowns"]["lxc"]["333"]
    assert latest["timeout_seconds"] == 30
    assert latest["timeout_ratio"] == 0.4


def test_guest_shutdown_assessment_is_app_owned_for_host_shutdown_journal(tmp_path):
    journal = {
        "text": (
            "2026-09-26T01:00:00+05:00 Stopping CT 149 (timeout = 20 seconds)\n"
            "2026-09-26T01:00:17+05:00 "
            "end task UPID:pve:1:2:3:4:vzshutdown:149:root@pam: OK\n"
        )
    }
    tracker = ShutdownHistoryTracker(
        state_store=StateStore(tmp_path / "shutdown.json"),
        boot_id_reader=lambda: "boot-a",
        boot_time_reader=lambda: "2026-09-26T00:00:00+05:00",
        previous_boot_journal_reader=lambda: "",
        current_boot_journal_reader=lambda: journal["text"],
    )
    tracker.startup()
    assert tracker.refresh_current_guest_shutdowns() is True

    latest = tracker.payload()["guest_last_shutdowns"]["lxc"]["149"]
    assert latest["duration_seconds"] == 17
    assert latest["timeout_ratio"] == 0.85
    assert latest["assessment"] == "warning"
