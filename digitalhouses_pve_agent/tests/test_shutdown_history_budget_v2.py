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


def test_standalone_guest_shutdown_fact_preserves_history_and_tracks_current_config(tmp_path):
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
    assert latest["current_timeout_seconds"] == 30
    assert latest["current_timeout_ratio"] == 0.4
    assert latest["current_assessment"] == "ok"

    # Historical facts keep the timeout from the shutdown event, while the
    # current-config assessment follows later PVE timeout changes.
    assert tracker.enrich_guest_last_shutdowns(
        {("lxc", "333"): 50}
    ) is True
    latest = tracker.payload()["guest_last_shutdowns"]["lxc"]["333"]
    assert latest["timeout_seconds"] == 30
    assert latest["timeout_ratio"] == 0.4
    assert latest["assessment"] == "ok"
    assert latest["current_timeout_seconds"] == 50
    assert latest["current_timeout_ratio"] == 0.24
    assert latest["current_assessment"] == "ok"


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


def test_legacy_history_guest_assessment_is_derived_from_stored_historical_facts(tmp_path):
    store = StateStore(tmp_path / "shutdown.json")
    store.save(
        {
            "current_boot": {
                "boot_id": "boot-current",
                "boot_at": "2026-09-26T02:00:00+05:00",
            },
            "history": [
                {
                    "boot_id": "boot-prev",
                    "shutdown_class": "normal",
                    "shutdown_clean": True,
                    "guests": {
                        "vm": {
                            "501": {
                                "kind": "vm",
                                "guest_id": "501",
                                "duration_seconds": 28,
                                "timeout_seconds": 30,
                                "timeout_ratio": None,
                                "result": "clean",
                                "forced": False,
                            }
                        },
                        "lxc": {
                            "10001": {
                                "kind": "lxc",
                                "guest_id": "10001",
                                "duration_seconds": 32,
                                "timeout_seconds": 30,
                                "result": "clean",
                                "forced": False,
                            }
                        },
                    },
                }
            ],
        }
    )
    tracker = ShutdownHistoryTracker(
        state_store=store,
        boot_id_reader=lambda: "boot-current",
        boot_time_reader=lambda: "2026-09-26T02:00:00+05:00",
        previous_boot_journal_reader=lambda: "",
    )

    tracker.startup()

    item = tracker.payload()["history"][0]
    plex = item["guests"]["vm"]["501"]
    wordpress = item["guests"]["lxc"]["10001"]

    assert plex["timeout_ratio"] == 0.933
    assert plex["assessment"] == "warning"
    assert wordpress["timeout_ratio"] == 1.067
    assert wordpress["assessment"] == "critical"

    persisted = store.load()["history"][0]
    assert persisted["guests"]["vm"]["501"]["assessment"] == "warning"
    assert persisted["guests"]["lxc"]["10001"]["assessment"] == "critical"


def test_guest_name_snapshot_is_carried_into_new_pve_shutdown_history(tmp_path):
    boot = {"id": "boot-a", "at": "2026-09-26T00:00:00+05:00"}
    journal = {
        "text": (
            "2026-09-26T01:00:00+05:00 The system will power off now\n"
            "2026-09-26T01:00:01+05:00 Stopping VM 110 (timeout = 125 seconds)\n"
            "2026-09-26T01:00:19+05:00 end task UPID:x:qmshutdown:110:root@pam: OK\n"
            "2026-09-26T01:00:20+05:00 Stopping CT 333 (timeout = 30 seconds)\n"
            "2026-09-26T01:00:32+05:00 end task UPID:x:vzshutdown:333:root@pam: OK\n"
            "2026-09-26T01:00:33+05:00 all VMs and CTs stopped\n"
            "2026-09-26T01:00:40+05:00 Reached target shutdown.target\n"
        )
    }
    tracker = ShutdownHistoryTracker(
        state_store=StateStore(tmp_path / "shutdown.json"),
        boot_id_reader=lambda: boot["id"],
        boot_time_reader=lambda: boot["at"],
        previous_boot_journal_reader=lambda: journal["text"],
    )
    tracker.startup()

    tracker.record_guest_inventory(
        {
            ("vm", "110"): "haos-asyl-mura",
            ("lxc", "333"): "NetAlertX",
        }
    )

    boot["id"] = "boot-b"
    boot["at"] = "2026-09-26T01:02:00+05:00"
    previous = tracker.startup()["previous_shutdown"]

    assert previous["guests"]["vm"]["110"]["name"] == "haos-asyl-mura"
    assert previous["guests"]["vm"]["110"]["assessment"] == "ok"
    assert previous["guests"]["lxc"]["333"]["name"] == "NetAlertX"
    assert previous["guests"]["lxc"]["333"]["assessment"] == "ok"


def test_guest_name_snapshot_does_not_rewrite_completed_history(tmp_path):
    boot = {"id": "boot-a", "at": "2026-09-26T00:00:00+05:00"}
    journal = {
        "text": (
            "2026-09-26T01:00:00+05:00 The system will power off now\n"
            "2026-09-26T01:00:01+05:00 Stopping CT 333 (timeout = 30 seconds)\n"
            "2026-09-26T01:00:13+05:00 end task UPID:x:vzshutdown:333:root@pam: OK\n"
            "2026-09-26T01:00:14+05:00 Reached target shutdown.target\n"
        )
    }
    tracker = ShutdownHistoryTracker(
        state_store=StateStore(tmp_path / "shutdown.json"),
        boot_id_reader=lambda: boot["id"],
        boot_time_reader=lambda: boot["at"],
        previous_boot_journal_reader=lambda: journal["text"],
    )
    tracker.startup()
    tracker.record_guest_inventory({("lxc", "333"): "NetAlertX"})

    boot["id"] = "boot-b"
    boot["at"] = "2026-09-26T01:02:00+05:00"
    tracker.startup()

    tracker.record_guest_inventory({("lxc", "333"): "Renamed Later"})

    history = tracker.payload()["history"]
    assert history[-1]["guests"]["lxc"]["333"]["name"] == "NetAlertX"
