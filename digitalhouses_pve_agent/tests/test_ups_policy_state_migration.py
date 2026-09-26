from pathlib import Path

from app.state_store import StateStore
from app.ups_policy_state_migration import migrate_retired_legacy_policy_state


ROOT = Path(__file__).resolve().parents[1]


def _legacy_state():
    return {
        "policy_active": {
            "on_battery_delay_minutes": 30,
            "power_restore_delay_seconds": 120,
        },
        "policy_draft": {
            "on_battery_delay_minutes": 45,
            "power_restore_delay_seconds": 180,
        },
        "policy_status": "Legacy policy",
        "policy_apply_result": "Политика UPS применена и проверена.",
        "policy_last_applied": "2026-09-15T10:00:00+05:00",
        "policy_revision": 7,
        "policy_hash": "legacy-hash",
        "keep_me": {"value": 1},
    }


def test_retired_dh_timer_normalizes_legacy_v1_policy_to_commissioning(tmp_path):
    store = StateStore(tmp_path / "ups_runtime.json")
    store.save(_legacy_state())
    upssched = tmp_path / "upssched.conf"
    upssched.write_text(
        "CMDSCRIPT /opt/digitalhouses/digitalhouses_pve_agent/bin/digitalhouses-pve-agent-ups-policy-cmd\n",
        encoding="utf-8",
    )

    changed = migrate_retired_legacy_policy_state(
        state_store=store,
        upssched_path=upssched,
    )

    assert changed is True
    state = store.load()
    assert state["policy_active"] is None
    assert state["policy_draft"] == {
        "shutdown_battery_charge_threshold_percent": 20,
        "runtime_reserve_seconds": 180,
    }
    assert state["policy_status"] == "Commissioning"
    assert state["policy_apply_result"] == "Not applied"
    assert state["policy_last_applied"] is None
    assert state["policy_revision"] == 0
    assert state["policy_hash"] is None
    assert state["keep_me"] == {"value": 1}


def test_active_dh_v1_timer_preserves_legacy_policy_state(tmp_path):
    store = StateStore(tmp_path / "ups_runtime.json")
    original = _legacy_state()
    store.save(original)
    upssched = tmp_path / "upssched.conf"
    upssched.write_text(
        "AT ONBATT * START-TIMER dh-pve-ups-shutdown 1800\n"
        "AT ONLINE * CANCEL-TIMER dh-pve-ups-shutdown\n",
        encoding="utf-8",
    )

    changed = migrate_retired_legacy_policy_state(
        state_store=store,
        upssched_path=upssched,
    )

    assert changed is False
    assert store.load() == original


def test_v2_policy_is_never_rewritten_by_legacy_migration(tmp_path):
    store = StateStore(tmp_path / "ups_runtime.json")
    state = {
        "policy_active": {
            "shutdown_battery_charge_threshold_percent": 25,
            "runtime_reserve_seconds": 600,
        },
        "policy_draft": {
            "shutdown_battery_charge_threshold_percent": 25,
            "runtime_reserve_seconds": 600,
        },
        "policy_status": "Active",
        "policy_apply_result": "Applied",
        "policy_revision": 3,
        "policy_hash": "v2-hash",
    }
    store.save(state)
    upssched = tmp_path / "upssched.conf"
    upssched.write_text("", encoding="utf-8")

    changed = migrate_retired_legacy_policy_state(
        state_store=store,
        upssched_path=upssched,
    )

    assert changed is False
    assert store.load() == state


def test_missing_upssched_file_counts_as_retired_only_for_legacy_state(tmp_path):
    store = StateStore(tmp_path / "ups_runtime.json")
    store.save(_legacy_state())

    changed = migrate_retired_legacy_policy_state(
        state_store=store,
        upssched_path=tmp_path / "missing-upssched.conf",
    )

    assert changed is True
    assert store.load()["policy_status"] == "Commissioning"


def test_systemd_runs_policy_state_migration_before_main_process():
    unit = (ROOT / "systemd" / "digitalhouses_pve_agent.service").read_text(encoding="utf-8")

    assert (
        "ExecStartPre=/opt/digitalhouses/digitalhouses_pve_agent/.venv/bin/python "
        "-m app.ups_policy_state_migration --state-dir /var/lib/digitalhouses_pve_agent"
    ) in unit
    assert unit.index("ExecStartPre=") < unit.index("ExecStart=")
