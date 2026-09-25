import subprocess

import pytest

from app.shutdown_history import ShutdownHistoryTracker, classify_previous_shutdown
from app.state_store import StateStore
from app.ups_nut import parse_upsc_output
from app.ups_shutdown_executor import (
    DEFAULT_POLICY_HELPER,
    SoftwareShutdownExecutionError,
    execute_fixed_ups_shutdown,
)


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_fixed_executor_invokes_only_immutable_helper_action_without_shell():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    execute_fixed_ups_shutdown("charge_guard", runner=runner)

    assert calls == [
        (
            [str(DEFAULT_POLICY_HELPER), "dh-pve-ups-shutdown"],
            {
                "capture_output": True,
                "text": True,
                "timeout": 5.0,
                "check": False,
            },
        )
    ]


def test_fixed_executor_accepts_only_canonical_software_trigger_reasons():
    called = []

    def runner(command, **kwargs):
        called.append(command)
        return Completed()

    with pytest.raises(SoftwareShutdownExecutionError, match="reason"):
        execute_fixed_ups_shutdown("manual", runner=runner)

    assert called == []


def test_fixed_executor_fails_closed_on_nonzero_or_timeout():
    with pytest.raises(SoftwareShutdownExecutionError, match="helper"):
        execute_fixed_ups_shutdown(
            "runtime_guard",
            runner=lambda command, **kwargs: Completed(returncode=1, stderr="denied"),
        )

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    with pytest.raises(SoftwareShutdownExecutionError, match="helper"):
        execute_fixed_ups_shutdown("runtime_guard", runner=timeout)


def test_tracker_records_successful_software_shutdown_commit_and_classifies_next_boot(tmp_path):
    clock = {"iso": "2026-09-16T01:10:00+05:00"}
    store = StateStore(tmp_path / "shutdown.json")
    tracker = ShutdownHistoryTracker(
        state_store=store,
        boot_id_reader=lambda: "boot-a",
        boot_time_reader=lambda: "2026-09-16T00:00:00+05:00",
        previous_boot_journal_reader=lambda: "",
        now_iso=lambda: clock["iso"],
    )
    tracker.startup()
    snapshot = parse_upsc_output(
        "ups.status: OB DISCHRG\nbattery.charge: 19\nbattery.runtime: 900\nups.load: 12\n"
    )

    tracker.record_software_shutdown_commit("charge_guard", snapshot)
    tracker.record_software_shutdown_commit("runtime_guard", snapshot)

    current = tracker.payload()["current_boot"]
    assert current["fsd_reason"] == "charge_guard"
    assert current["fsd_at"] == "2026-09-16T01:10:00+05:00"
    assert current["ups_status_at_fsd"] == "OB DISCHRG"
    assert current["battery_charge_at_fsd"] == 19.0
    assert current["battery_runtime_at_fsd"] == 900.0
    assert current["ups_load_at_fsd"] == 12.0
    assert classify_previous_shutdown(clean_shutdown=True, fsd_reason="charge_guard") == (
        "ups_power",
        "charge_guard",
    )
    assert classify_previous_shutdown(clean_shutdown=True, fsd_reason="runtime_guard") == (
        "ups_power",
        "runtime_guard",
    )
