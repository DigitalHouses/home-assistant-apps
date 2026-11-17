from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.collectors.cooling import FanSnapshot, _with_k15_fallback
from app.fan_hardware_gmktec_k15 import (
    collect_k15_ec_fans,
    is_k15,
    read_k15_ec_rpm,
)
from app.fan_presence import FanPresenceTracker
from app.fan_hardware_hwmon import HwmonPwmFanAdapter


def fixture(tmp_path: Path, raw: bytes = bytes.fromhex("05 07 06 ab")):
    dmi = tmp_path / "dmi"
    dmi.mkdir()
    (dmi / "product_name").write_text("NucBox_K15\n", encoding="ascii")
    ec = tmp_path / "io"
    ec.write_bytes(bytes(0x35) + raw)
    write_support = tmp_path / "write_support"
    write_support.write_text("N\n", encoding="ascii")
    return dmi, ec, write_support


def sample(dmi: Path, ec: Path, write_support: Path):
    return collect_k15_ec_fans(
        dmi_root=dmi, ec_file=ec, write_support_file=write_support
    )


def test_k15_dmi_exact_match_and_no_unknown_ec_access(tmp_path: Path):
    dmi, ec, flag = fixture(tmp_path)
    assert is_k15(dmi)
    assert [fan.rpm for fan in sample(dmi, ec, flag)] == [1287, 1707]
    (dmi / "product_name").write_text("NucBox_K12\n", encoding="ascii")
    ec.unlink()
    assert not is_k15(dmi)
    assert sample(dmi, ec, flag) == ()
    (dmi / "product_name").write_text("NucBox_K15_v2\n", encoding="ascii")
    assert sample(dmi, ec, flag) == ()


def test_k15_expected_fan_ids_labels_and_no_pwm_adapter(tmp_path: Path):
    dmi, ec, flag = fixture(tmp_path)
    fans = sample(dmi, ec, flag)
    assert [fan.fan_id for fan in fans] == [
        "gmktec_k15_ec_ec0_fan1", "gmktec_k15_ec_ec0_fan2"
    ]
    assert [fan.label for fan in fans] == ["CPU FAN", "FAN2"]
    assert [fan.available for fan in fans] == [True, True]
    assert all(fan.chip == "gmktec_k15_ec" for fan in fans)
    assert all(not HwmonPwmFanAdapter().supports(fan) for fan in fans)
    tracker = FanPresenceTracker()
    assert tracker.observe(fans).confirmed_count == 0
    assert tracker.observe(fans).confirmed_count == 2


def test_ec_interface_missing_or_kernel_write_enabled_is_unavailable(tmp_path: Path):
    dmi, ec, flag = fixture(tmp_path)
    ec.unlink()
    assert [fan.rpm for fan in sample(dmi, ec, flag)] == [None, None]
    assert not any(fan.available for fan in sample(dmi, ec, flag))
    ec.write_bytes(bytes(0x35) + bytes.fromhex("05 07 06 ab"))
    flag.write_text("Y\n", encoding="ascii")
    assert read_k15_ec_rpm(ec_file=ec, write_support_file=flag) == (None, None)
    flag.unlink()
    assert read_k15_ec_rpm(ec_file=ec, write_support_file=flag) == (None, None)


def test_bad_ec_payload_never_fabricates_zero_rpm(tmp_path: Path):
    dmi, ec, flag = fixture(tmp_path, raw=bytes.fromhex("ff ff 06 ab"))
    assert read_k15_ec_rpm(ec_file=ec, write_support_file=flag) == (None, None)
    ec.write_bytes(bytes(0x35) + bytes.fromhex("00 00 00 00"))
    assert read_k15_ec_rpm(ec_file=ec, write_support_file=flag) == (None, None)
    ec.write_bytes(bytes(0x35) + b"\x05")
    assert read_k15_ec_rpm(ec_file=ec, write_support_file=flag) == (None, None)


def test_real_zero_cpu_fan_is_preserved_when_second_channel_is_running(tmp_path: Path):
    dmi, ec, flag = fixture(tmp_path, raw=bytes.fromhex("00 00 06 ab"))
    assert read_k15_ec_rpm(ec_file=ec, write_support_file=flag) == (0, 1707)


class TornEc:
    def __init__(self, first: bytes, second: bytes):
        self.samples = iter((first, second))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def seek(self, *_):
        return None

    def read(self, amount: int):
        assert amount == 4
        return next(self.samples)


class EcFile:
    def __init__(self, first: bytes, second: bytes):
        self.first, self.second = first, second

    def open(self, mode: str):
        assert mode == "rb"
        return TornEc(self.first, self.second)


def test_torn_multibyte_sample_rejected_without_retry_loop(tmp_path: Path):
    _dmi, _ec, flag = fixture(tmp_path)
    source = EcFile(bytes.fromhex("05 07 06 ab"), bytes.fromhex("0a 10 06 ab"))
    assert read_k15_ec_rpm(ec_file=source, write_support_file=flag) == (None, None)


def test_lost_ec_keeps_confirmed_identity_but_marks_rpm_unavailable(tmp_path: Path):
    dmi, ec, flag = fixture(tmp_path)
    tracker = FanPresenceTracker()
    tracker.observe(sample(dmi, ec, flag))
    assert tracker.observe(sample(dmi, ec, flag)).confirmed_count == 2
    ec.unlink()
    status = tracker.observe(sample(dmi, ec, flag))
    assert status.confirmed_count == 2
    assert all(fan.rpm is None and not fan.available for fan in status.confirmed_fans)


def test_k15_fallback_is_used_only_without_existing_board_channel(tmp_path: Path):
    dmi, ec, flag = fixture(tmp_path)
    k15 = sample(dmi, ec, flag)
    gpu = replace(k15[0], fan_id="xe_gpu_fan1", chip="xe")
    board = replace(k15[0], fan_id="nct6798_board_fan1", chip="nct6798", rpm=0)
    with patch("app.fan_hardware_gmktec_k15.collect_k15_ec_fans", return_value=k15) as reader:
        assert _with_k15_fallback(Path("/sys/class/hwmon"), ()) == k15
        assert _with_k15_fallback(Path("/sys/class/hwmon"), (gpu,)) == (gpu, *k15)
        reader.reset_mock()
        assert _with_k15_fallback(Path("/sys/class/hwmon"), (board,)) == (board,)
        assert _with_k15_fallback(Path("/tmp/hwmon"), ()) == ()
        reader.assert_not_called()
