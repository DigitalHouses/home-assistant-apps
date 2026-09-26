from app.shutdown_history import ShutdownHistoryTracker
from app.state_store import StateStore


def test_0527_projection_keys_migrate_only_in_latest_guest_state(tmp_path):
    store = StateStore(tmp_path / "shutdown.json")
    legacy_fact = {
        "kind": "vm",
        "guest_id": "501",
        "duration_seconds": 28,
        "timeout_seconds": 30,
        "timeout_ratio": 0.933,
        "assessment": "warning",
        "result": "clean",
        "forced": False,
        "current_timeout_seconds": 70,
        "current_timeout_ratio": 0.4,
        "current_assessment": "ok",
    }
    store.save(
        {
            "current_boot": {
                "boot_id": "boot-current",
                "boot_at": "2026-09-26T02:00:00+05:00",
            },
            "guest_last_shutdowns": {
                "vm": {"501": dict(legacy_fact)},
                "lxc": {},
            },
            "history": [
                {
                    "boot_id": "boot-prev",
                    "shutdown_class": "normal",
                    "shutdown_clean": True,
                    "guests": {
                        "vm": {"501": dict(legacy_fact)},
                        "lxc": {},
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
    payload = tracker.payload()

    latest = payload["guest_last_shutdowns"]["vm"]["501"]
    assert latest["next_shutdown_timeout_seconds"] == 70
    assert latest["next_shutdown_timeout_ratio"] == 0.4
    assert latest["next_shutdown_assessment"] == "ok"
    assert "current_timeout_seconds" not in latest
    assert "current_timeout_ratio" not in latest
    assert "current_assessment" not in latest

    historical = payload["history"][0]["guests"]["vm"]["501"]
    assert "next_shutdown_timeout_seconds" not in historical
    assert "next_shutdown_timeout_ratio" not in historical
    assert "next_shutdown_assessment" not in historical
    assert "current_timeout_seconds" not in historical
    assert "current_timeout_ratio" not in historical
    assert "current_assessment" not in historical
