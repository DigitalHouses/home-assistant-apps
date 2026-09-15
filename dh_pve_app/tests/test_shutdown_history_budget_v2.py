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
