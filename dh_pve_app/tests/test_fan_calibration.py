from pathlib import Path

from app.collectors.cooling import FanSnapshot
from app.fan_calibration import FanCalibrationManager, FanCalibrationRegistry
from app.state_store import StateStore


class FakeAdapter:
    profile_name = "fake_profile"

    def __init__(self, rpms, *, supported=True, restore_error=False, original_pwm="95"):
        self.rpms = iter(rpms)
        self.supported = supported
        self.restore_error = restore_error
        self.original = {"pwm": original_pwm, "pwm_enable": "2"}
        self.writes = []
        self.restores = 0

    def supports(self, fan):
        return self.supported

    def hardware_identity(self, fan):
        return "hardware-A"

    def capture(self, fan):
        return dict(self.original)

    def enter_max(self, fan):
        self.writes.append(("max", fan.fan_id))

    def read_rpm(self, fan):
        return next(self.rpms)

    def restore(self, fan, original):
        self.restores += 1
        if self.restore_error:
            raise OSError("restore failed")
        assert original == self.original

    def verify_restored(self, fan, original):
        return not self.restore_error

    def original_is_max(self, original):
        return int(original["pwm"]) >= 250


def _fan(rpm=3729):
    return FanSnapshot(
        fan_id="it8613_it87_2608_fan2",
        chip="it8613",
        chip_display_name="it8613",
        source_device="it87.2608",
        fan_name="fan2",
        fan_index=2,
        label="Fan 2",
        display_name="Fan 2 RPM - it8613",
        rpm=rpm,
        available=True,
        input_path="/sys/class/hwmon/hwmon3/fan2_input",
    )


def test_no_calibration_state_requests_first_run_calibration(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter([3729, 3729, 5400, 5400, 5400])

    assert registry.needs_automatic_calibration(_fan(), adapter) is True


def test_existing_valid_calibration_is_not_repeated(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter([3729])
    registry.save_calibration(
        _fan(), adapter, max_rpm=5400, calibrated_at="2026-09-22T01:00:00+05:00"
    )

    assert registry.needs_automatic_calibration(_fan(), adapter) is False


def test_calibration_reaches_stable_plateau_and_restores_original_state(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter([3729, 3729, 3729, 5400, 5400, 5400])
    manager = FanCalibrationManager(
        registry=registry,
        adapters=(adapter,),
        now_iso=lambda: "2026-09-22T01:10:00+05:00",
        sleep=lambda _seconds: None,
    )

    result = manager.calibrate((_fan(),), automatic=True)

    assert result["it8613_it87_2608_fan2"] == "calibrated"
    assert adapter.restores == 1
    record = registry.record(_fan(), adapter)
    assert record["max_rpm"] == 5400
    assert record["calibration_status"] == "calibrated"


def test_unstable_rpm_fails_but_restores(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter([3700, 4100, 4800, 4300, 5200, 4500, 5000, 4700] * 3)
    manager = FanCalibrationManager(
        registry=registry,
        adapters=(adapter,),
        now_iso=lambda: "2026-09-22T01:10:00+05:00",
        sleep=lambda _seconds: None,
    )

    result = manager.calibrate((_fan(),), automatic=True)

    assert result["it8613_it87_2608_fan2"] == "failed"
    assert adapter.restores == 1


def test_exception_still_restores_original_state(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter([3729, OSError("rpm unavailable")])

    def read_rpm(fan):
        value = next(adapter.rpms)
        if isinstance(value, Exception):
            raise value
        return value

    adapter.read_rpm = read_rpm
    manager = FanCalibrationManager(
        registry=registry,
        adapters=(adapter,),
        now_iso=lambda: "2026-09-22T01:10:00+05:00",
        sleep=lambda _seconds: None,
    )

    result = manager.calibrate((_fan(),), automatic=True)

    assert result["it8613_it87_2608_fan2"] == "failed"
    assert adapter.restores == 1


def test_restore_failure_is_separate_serious_status(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter(
        [3729, 3729, 3729, 5400, 5400, 5400],
        restore_error=True,
    )
    manager = FanCalibrationManager(
        registry=registry,
        adapters=(adapter,),
        now_iso=lambda: "2026-09-22T01:10:00+05:00",
        sleep=lambda _seconds: None,
    )

    result = manager.calibrate((_fan(),), automatic=True)

    assert result["it8613_it87_2608_fan2"] == "restore_failed"
    assert registry.record(_fan(), adapter)["calibration_status"] == "restore_failed"


def test_percent_uses_calibrated_physical_max_and_clamps(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter([0])
    registry.save_calibration(
        _fan(), adapter, max_rpm=5400, calibrated_at="2026-09-22T01:00:00+05:00"
    )

    assert registry.presentation(_fan(2700), adapter)["speed_percent"] == 50
    assert registry.presentation(_fan(0), adapter)["speed_percent"] == 0
    assert registry.presentation(_fan(6000), adapter)["speed_percent"] == 100


def test_missing_calibration_makes_percent_unavailable(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter([0])

    assert registry.presentation(_fan(2700), adapter)["speed_percent"] is None


def test_unsupported_hardware_never_enters_max_control(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter([3729], supported=False)
    manager = FanCalibrationManager(
        registry=registry,
        adapters=(adapter,),
        now_iso=lambda: "2026-09-22T01:10:00+05:00",
        sleep=lambda _seconds: None,
    )

    assert manager.calibrate((_fan(),), automatic=True) == {}
    assert adapter.writes == []


def test_manual_and_automatic_paths_use_same_calibration_use_case(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter([3729, 3729, 3729, 5400, 5400, 5400])
    manager = FanCalibrationManager(
        registry=registry,
        adapters=(adapter,),
        now_iso=lambda: "2026-09-22T01:10:00+05:00",
        sleep=lambda _seconds: None,
    )
    assert manager.calibrate((_fan(),), automatic=True)[_fan().fan_id] == "calibrated"

    adapter.rpms = iter([5400, 5400, 5500, 5500, 5500])
    assert manager.calibrate((_fan(),), automatic=False)[_fan().fan_id] == "calibrated"
    assert registry.record(_fan(), adapter)["max_rpm"] == 5500


def test_concurrent_calibration_is_rejected(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter([3729])
    manager = FanCalibrationManager(
        registry=registry,
        adapters=(adapter,),
        now_iso=lambda: "2026-09-22T01:10:00+05:00",
        sleep=lambda _seconds: None,
    )
    assert manager._lock.acquire(blocking=False) is True
    try:
        assert manager.calibrate((_fan(),), automatic=False) == {"_status": "busy"}
    finally:
        manager._lock.release()


def test_sustained_observed_rpm_can_raise_but_never_lower_max(tmp_path: Path):
    registry = FanCalibrationRegistry(StateStore(tmp_path / "fan_calibration.json"))
    adapter = FakeAdapter([0])
    registry.save_calibration(
        _fan(), adapter, max_rpm=5400, calibrated_at="2026-09-22T01:00:00+05:00"
    )

    registry.presentation(_fan(5600), adapter, observed_at="2026-09-22T02:00:00+05:00")
    assert registry.record(_fan(), adapter)["max_rpm"] == 5400
    registry.presentation(_fan(5590), adapter, observed_at="2026-09-22T02:00:10+05:00")
    registry.presentation(_fan(5610), adapter, observed_at="2026-09-22T02:00:20+05:00")
    assert registry.record(_fan(), adapter)["max_rpm"] == 5600
    assert registry.record(_fan(), adapter)["max_rpm_source"] == "observed"

    registry.presentation(_fan(4000), adapter, observed_at="2026-09-22T03:00:00+05:00")
    assert registry.record(_fan(), adapter)["max_rpm"] == 5600
