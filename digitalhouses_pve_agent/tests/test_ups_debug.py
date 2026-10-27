"""UPS debug is an optional bounded diagnostic, not another safety controller."""
import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.config import UpsConfig
from app.ups_debug import MAX_DEBUG_SECONDS, UpsDebugRecorder
from app.ups_nut import parse_upsc_output


def _snapshot(status="OL CHRG", charge=90):
    return parse_upsc_output(
        f"ups.status: {status}\nbattery.charge: {charge}\n"
        "battery.runtime: 3240\nups.load: 0\n"
        "battery.voltage: 27.4\ninput.voltage: 225\n"
    )


def _config():
    return UpsConfig(enabled=True, name="ups", host="127.0.0.1")


def _new(tmp_path, clock, sample_seconds=0.01):
    return UpsDebugRecorder(
        tmp_path, _config(), reader=lambda _: _snapshot(),
        now=lambda: clock[0], sample_seconds=sample_seconds,
    )


def test_off_by_default_does_not_create_log(tmp_path):
    clock = [datetime(2026, 10, 27, tzinfo=timezone.utc)]
    recorder = _new(tmp_path, clock)
    try:
        assert recorder.enabled() is False
        time.sleep(0.03)
        assert not (tmp_path / "dh_ups_debug.log").exists()
    finally:
        recorder.close()


def test_72_hour_expiration_persisted_across_restart(tmp_path):
    clock = [datetime(2026, 10, 27, tzinfo=timezone.utc)]
    recorder = _new(tmp_path, clock)
    assert recorder.set_enabled(True) is True
    recorder.close()
    saved = json.loads((tmp_path / "ups_debug_state.json").read_text())
    assert datetime.fromisoformat(saved["expires_at"]) == clock[0] + timedelta(seconds=MAX_DEBUG_SECONDS)

    clock[0] += timedelta(hours=71)
    restarted = _new(tmp_path, clock)
    try:
        assert restarted.enabled() is True
        clock[0] += timedelta(hours=2)
        assert restarted.enabled() is False
        state = json.loads((tmp_path / "ups_debug_state.json").read_text())
        assert state["enabled"] is False
    finally:
        restarted.close()


def test_enable_write_snapshot_and_explicit_off(tmp_path):
    clock = [datetime(2026, 10, 27, tzinfo=timezone.utc)]
    recorder = _new(tmp_path, clock)
    try:
        assert recorder.set_enabled(True)
        limit = time.monotonic() + 1
        while time.monotonic() < limit:
            path = tmp_path / "dh_ups_debug.log"
            if path.exists() and '"kind":"nut_sample"' in path.read_text():
                break
            time.sleep(0.01)
        else:
            assert False, "debugger did not record a sample"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        samples = [x for x in records if x["kind"] == "nut_sample"]
        assert samples[0]["status_raw"] == "OL CHRG"
        assert samples[0]["battery_charge_percent"] == 90.0
        assert samples[0]["load_percent"] == 0.0
        assert recorder.set_enabled(False) is False
        assert recorder.enabled() is False
    finally:
        recorder.close()


def test_fsd_intent_recorded_without_calling_any_ups_command(tmp_path):
    clock = [datetime(2026, 10, 27, tzinfo=timezone.utc)]
    recorder = _new(tmp_path, clock, sample_seconds=10)
    try:
        recorder.set_enabled(True)
        recorder.record_software_fsd(
            "charge_guard", _snapshot("OB", 0),
            type("Policy", (), {"shutdown_battery_charge_threshold_percent": 20,
                               "runtime_reserve_seconds": 180})(),
            type("Budget", (), {"shutdown_budget_seconds": 450})(),
        )
        data = (tmp_path / "dh_ups_debug.log").read_text()
        assert '"kind":"software_fsd_intent"' in data
        assert '"battery_charge_percent":0.0' in data
        assert '"charge_threshold_percent":20' in data
    finally:
        recorder.close()


def test_enable_without_selected_ups_is_denied(tmp_path):
    recorder = UpsDebugRecorder(tmp_path, None)
    try:
        assert recorder.set_enabled(True) is False
        assert recorder.enabled() is False
    finally:
        recorder.close()
