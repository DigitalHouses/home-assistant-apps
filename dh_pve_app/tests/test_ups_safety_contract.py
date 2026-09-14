import inspect
from pathlib import Path

from app.ups_control import _BATTERY_TEST_COMMANDS, run_ups_battery_test
from app.ups_nut import read_ups

ROOT = Path(__file__).resolve().parents[1]


def test_control_surface_is_limited_to_battery_tests():
    assert _BATTERY_TEST_COMMANDS == {
        "quick": "test.battery.start.quick",
        "deep": "test.battery.start.deep",
        "stop": "test.battery.stop",
    }

    executor_text = inspect.getsource(run_ups_battery_test)
    for forbidden in (
        "load.off",
        "load.on",
        "shutdown.return",
        "shutdown.stayoff",
        "FSD",
        "poweroff",
        "shutdown -h",
    ):
        assert forbidden not in executor_text


def test_installer_does_not_configure_or_control_nut():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "/etc/nut" not in text
    assert "nut-monitor" not in text
    assert "nut-server" not in text
    assert "upsmon" not in text


def test_ups_telemetry_reader_remains_read_only_upsc_backend():
    text = inspect.getsource(read_ups)
    assert '["upsc", f"{config.name}@{config.host}:{config.port}"]' in text
    assert "upscmd" not in text
    assert "upsrw" not in text
