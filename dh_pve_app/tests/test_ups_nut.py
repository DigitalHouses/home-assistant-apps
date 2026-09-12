from pathlib import Path
import subprocess

import pytest

from app.config import UpsConfig
from app.ups_nut import NutReadError, parse_upsc_output, read_ups, ups_metrics

FIX = Path(__file__).parent / "fixtures" / "ups" / "cyberpower_ut2200e.upsc"


def test_parse_remote_cyberpower_sample():
    snapshot = parse_upsc_output(FIX.read_text(encoding="utf-8"))

    assert snapshot.manufacturer == "CPS"
    assert snapshot.model == "UT2200E"
    assert snapshot.status_raw == "OL"
    assert snapshot.status_tokens == ("OL",)
    assert snapshot.line_power is True
    assert snapshot.on_battery is False
    assert snapshot.low_battery is False
    assert snapshot.battery_charge_percent == 100.0
    assert snapshot.runtime_seconds == 2160.0
    assert snapshot.battery_voltage_v == 27.2
    assert snapshot.load_percent == 8.0
    assert snapshot.nominal_real_power_w == 1320.0
    assert not hasattr(snapshot, "estimated_real_power_w")
    assert snapshot.input_voltage_v == 221.0
    assert snapshot.output_voltage_v == 221.0
    assert snapshot.warning_charge_percent == 20.0
    assert snapshot.low_charge_percent == 10.0
    assert snapshot.low_runtime_seconds == 300.0
    assert snapshot.input_transfer_high_v is None
    assert snapshot.input_transfer_low_v is None


def test_multi_token_status_is_normalized():
    snapshot = parse_upsc_output("ups.status: OB LB DISCHRG\n")

    assert snapshot.status_tokens == ("OB", "LB", "DISCHRG")
    assert snapshot.line_power is False
    assert snapshot.on_battery is True
    assert snapshot.low_battery is True
    assert snapshot.discharging is True
    assert snapshot.charging is False


def test_unknown_status_tokens_are_preserved():
    snapshot = parse_upsc_output("ups.status: OL X-NEW\n")

    assert snapshot.status_tokens == ("OL", "X-NEW")
    assert snapshot.line_power is True


def test_missing_and_malformed_optional_values_do_not_break_snapshot():
    snapshot = parse_upsc_output(
        "device.model: Demo\n"
        "ups.status: OL\n"
        "battery.charge: not-a-number\n"
        "ups.load: \n"
    )

    assert snapshot.model == "Demo"
    assert snapshot.battery_charge_percent is None
    assert snapshot.load_percent is None
    assert not hasattr(snapshot, "estimated_real_power_w")


def test_ups_metrics_use_expected_publish_policies():
    snapshot = parse_upsc_output(FIX.read_text(encoding="utf-8"))
    metrics = ups_metrics(snapshot)

    assert metrics["status"].policy == "discrete"
    assert metrics["on_battery"].policy == "discrete"
    assert metrics["battery_charge_percent"].policy == "ups_charge_online"
    assert metrics["load_percent"].policy == "ups_load_online"
    assert metrics["runtime_seconds"].policy == "ups_runtime_online"
    assert metrics["input_voltage_v"].policy == "ups_voltage_online"
    assert metrics["beeper_status"].policy == "discrete"
    assert metrics["test_result"].policy == "discrete"


def test_read_ups_calls_only_upsc_with_bounded_timeout():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="ups.status: OL\n", stderr="")

    config = UpsConfig(
        enabled=True,
        name="rackups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=5.0,
        command_timeout_seconds=2.5,
    )
    snapshot = read_ups(config, runner=runner)

    assert snapshot.status_raw == "OL"
    assert calls == [(
        ["upsc", "rackups@127.0.0.1:3493"],
        {
            "capture_output": True,
            "text": True,
            "timeout": 2.5,
            "check": True,
        },
    )]


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError("upsc"),
        subprocess.TimeoutExpired(["upsc"], 3),
        subprocess.CalledProcessError(1, ["upsc"], stderr="ERR UNKNOWN-UPS"),
    ],
)
def test_read_ups_converts_command_failures_to_nut_read_error(exc):
    def runner(command, **kwargs):
        raise exc

    with pytest.raises(NutReadError):
        read_ups(UpsConfig(enabled=True), runner=runner)
