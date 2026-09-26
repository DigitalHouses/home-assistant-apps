from app.state_store import StateStore
from app.ups_policy_state_migration import migrate_retired_legacy_policy_state


def test_runtime_normalized_legacy_status_migrates_after_timer_retired(tmp_path):
    store = StateStore(tmp_path / "ups_runtime.json")
    store.save(
        {
            "policy_status": "Legacy policy",
            "policy_active": None,
            "policy_draft": {
                "runtime_reserve_seconds": 180,
                "shutdown_battery_charge_threshold_percent": 20,
            },
            "policy_apply_result": "Политика UPS применена и проверена.",
            "policy_last_applied": None,
            "policy_revision": 0,
            "policy_hash": None,
        }
    )
    upssched = tmp_path / "upssched.conf"
    upssched.write_text(
        "CMDSCRIPT /opt/digitalhouses/digitalhouses_pve_agent/bin/digitalhouses-pve-agent-ups-policy-cmd\n"
        "PIPEFN /run/nut/upssched.pipe\n"
        "LOCKFN /run/nut/upssched.lock\n",
        encoding="utf-8",
    )

    assert migrate_retired_legacy_policy_state(
        state_store=store,
        upssched_path=upssched,
    ) is True

    state = store.load()
    assert state["policy_status"] == "Commissioning"
    assert state["policy_active"] is None
    assert state["policy_draft"] == {
        "runtime_reserve_seconds": 180,
        "shutdown_battery_charge_threshold_percent": 20,
    }
    assert state["policy_apply_result"] == "Not applied"
    assert state["policy_last_applied"] is None
    assert state["policy_revision"] == 0
    assert state["policy_hash"] is None
