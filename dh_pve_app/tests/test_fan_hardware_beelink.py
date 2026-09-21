from pathlib import Path

from app.collectors.cooling import FanSnapshot
from app.fan_hardware_beelink import BeelinkIt8613FanAdapter


def _fan(hwmon: Path, *, fan_index: int = 2) -> FanSnapshot:
    input_path = hwmon / f"fan{fan_index}_input"
    return FanSnapshot(
        fan_id=f"it8613_it87_2608_fan{fan_index}",
        chip="it8613",
        chip_display_name="it8613",
        source_device="it87.2608",
        fan_name=f"fan{fan_index}",
        fan_index=fan_index,
        label=f"Fan {fan_index}",
        display_name=f"Fan {fan_index} RPM - it8613",
        rpm=3729,
        available=True,
        input_path=str(input_path),
    )


def _profile(tmp_path: Path, *, vendor: str = "AZW"):
    dmi = tmp_path / "dmi"
    dmi.mkdir()
    (dmi / "sys_vendor").write_text(vendor + "\n", encoding="utf-8")
    (dmi / "product_name").write_text("MINI S\n", encoding="utf-8")
    (dmi / "board_vendor").write_text(vendor + "\n", encoding="utf-8")
    (dmi / "board_name").write_text("ADL-N\n", encoding="utf-8")

    hwmon = tmp_path / "hwmon3"
    hwmon.mkdir()
    (hwmon / "fan2_input").write_text("3729\n", encoding="utf-8")
    (hwmon / "pwm2").write_text("95\n", encoding="utf-8")
    (hwmon / "pwm2_enable").write_text("2\n", encoding="utf-8")
    return BeelinkIt8613FanAdapter(dmi_root=dmi), hwmon


def test_beelink_adapter_requires_exact_supported_profile(tmp_path: Path):
    adapter, hwmon = _profile(tmp_path)
    assert adapter.supports(_fan(hwmon)) is True
    assert adapter.supports(_fan(hwmon, fan_index=3)) is False

    unsupported, other_hwmon = _profile(tmp_path / "other", vendor="OtherVendor")
    assert unsupported.supports(_fan(other_hwmon)) is False


def test_beelink_adapter_captures_enters_max_and_restores_fake_sysfs(tmp_path: Path):
    adapter, hwmon = _profile(tmp_path)
    fan = _fan(hwmon)

    original = adapter.capture(fan)
    assert original == {"pwm": "95", "pwm_enable": "2"}

    adapter.enter_max(fan)
    assert (hwmon / "pwm2").read_text(encoding="utf-8").strip() == "255"
    assert (hwmon / "pwm2_enable").read_text(encoding="utf-8").strip() == "1"

    adapter.restore(fan, original)
    assert adapter.verify_restored(fan, original) is True
    assert (hwmon / "pwm2").read_text(encoding="utf-8").strip() == "95"
    assert (hwmon / "pwm2_enable").read_text(encoding="utf-8").strip() == "2"


def test_beelink_adapter_never_touches_pwm_when_profile_is_unsupported(tmp_path: Path):
    adapter, hwmon = _profile(tmp_path, vendor="OtherVendor")
    fan = _fan(hwmon)
    before_pwm = (hwmon / "pwm2").read_text(encoding="utf-8")
    before_enable = (hwmon / "pwm2_enable").read_text(encoding="utf-8")

    assert adapter.supports(fan) is False
    assert (hwmon / "pwm2").read_text(encoding="utf-8") == before_pwm
    assert (hwmon / "pwm2_enable").read_text(encoding="utf-8") == before_enable


def test_hardware_identity_changes_when_dmi_changes(tmp_path: Path):
    adapter, hwmon = _profile(tmp_path)
    fan = _fan(hwmon)
    first = adapter.hardware_identity(fan)

    (adapter.dmi_root / "product_name").write_text("Different Model\n", encoding="utf-8")
    second = adapter.hardware_identity(fan)

    assert first != second
