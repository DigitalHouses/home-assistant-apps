from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.collectors import cooling
from app.fan_presence import FanPresenceTracker


BMC_FAN_SDR = """
FAN1             | 60h | ok  |  7.0 | 1700 RPM
FAN2             | 61h | ns  |  7.0 | No Reading
FAN3             | 62h | ok  |  7.0 | 900 RPM
FAN4_1           | 63h | ns  |  7.0 | No Reading
FAN4_2           | 66h | ns  |  7.0 | No Reading
PSU1 Fan         | 78h | ns  |  7.0 | No Reading
PSU2 Fan Status  | 80h | ok  |  7.0 | 0x0000
"""


class TestBmcIpmiFanDiscovery(TestCase):
    def test_only_real_fan_rpm_becomes_candidate(self):
        fans = cooling.parse_ipmi_fan_sdr(BMC_FAN_SDR)
        self.assertEqual(
            [f.fan_id for f in fans],
            ["ipmi_ipmi0_fan1", "ipmi_ipmi0_fan3"],
        )
        self.assertEqual([f.rpm for f in fans], [1700, 900])
        self.assertEqual([f.label for f in fans], ["FAN1", "FAN3"])
        self.assertTrue(
            all(f.chip == "ipmi" and f.source_device == "ipmi0" for f in fans)
        )
        self.assertTrue(all(f.available for f in fans))

    def test_existing_two_positive_samples_confirm_the_two_bmc_fans(self):
        tracker = FanPresenceTracker()
        parsed = cooling.parse_ipmi_fan_sdr(BMC_FAN_SDR)
        first = tracker.observe(parsed)
        second = tracker.observe(parsed)
        self.assertEqual(first.candidate_count, 2)
        self.assertEqual(first.confirmed_count, 0)
        self.assertEqual(second.confirmed_count, 2)
        self.assertEqual([f.label for f in second.confirmed_fans], ["FAN1", "FAN3"])

    def test_zero_rpm_remains_reportable_after_confirmation(self):
        fan = cooling.parse_ipmi_fan_sdr(
            "FAN1 | 60h | ok | 7.0 | 0 RPM"
        )[0]
        self.assertEqual(fan.rpm, 0)
        self.assertTrue(fan.available)

    def test_ignore_missing_invalid_and_duplicate_readings(self):
        output = (
            "FAN1 | 60h | ns | 7.0 | No Reading\n"
            "FAN2 | 61h | ok | 7.0 | 900 RPM\n"
            "FAN2 | 61h | ok | 7.0 | 800 RPM\n"
            "FAN3 | 62h | ok | 7.0 | 150 C\n"
            "FAN4 | 63h | cr | 7.0 | 200 RPM\n"
            "FAN5 | 64h | ok | 7.0 | -1 RPM\n"
            "PSU1 Fan | 78h | ok | 7.0 | 250 RPM\n"
        )
        fans = cooling.parse_ipmi_fan_sdr(output)
        self.assertEqual(
            [f.fan_id for f in fans],
            ["ipmi_ipmi0_fan2", "ipmi_ipmi0_psu1_fan"],
        )
        self.assertEqual([f.rpm for f in fans], [900, 250])

    def test_only_local_read_only_ipmi_command_and_no_network(self):
        with TemporaryDirectory() as tmp:
            ipmi_device = Path(tmp) / "ipmi0"
            self.assertEqual(cooling.collect_ipmi_fans(ipmi_device), ())
            ipmi_device.touch()
            with patch.object(
                cooling.subprocess, "run",
                return_value=CompletedProcess([], 0, BMC_FAN_SDR, ""),
            ) as call:
                fans = cooling.collect_ipmi_fans(ipmi_device)
            self.assertEqual(len(fans), 2)
            call.assert_called_once_with(
                ["ipmitool", "-I", "open", "sdr", "type", "Fan"],
                check=True, capture_output=True, text=True, timeout=6,
            )

    def test_fails_closed_when_ipmi_is_missing_or_times_out(self):
        with TemporaryDirectory() as tmp:
            ipmi_device = Path(tmp) / "ipmi0"
            ipmi_device.touch()
            for failure in (
                FileNotFoundError("ipmitool"),
                TimeoutExpired("ipmitool", 6),
                CalledProcessError(1, "ipmitool"),
            ):
                with self.subTest(failure=type(failure).__name__):
                    with patch.object(
                        cooling.subprocess, "run", side_effect=failure
                    ):
                        self.assertEqual(cooling.collect_ipmi_fans(ipmi_device), ())

    def test_sysfs_fan_preserves_existing_collector_behavior(self):
        with TemporaryDirectory() as tmp:
            hwmon_root = Path(tmp)
            hw = hwmon_root / "hwmon0"
            hw.mkdir()
            (hw / "name").write_text("nct6798\n")
            (hw / "fan1_input").write_text("1020\n")
            with patch.object(
                cooling, "collect_ipmi_fans",
                side_effect=AssertionError("IPMI should not run"),
            ):
                fans = cooling.collect_fans(hwmon_root)
            self.assertEqual(len(fans), 1)
            self.assertEqual(fans[0].chip, "nct6798")
            self.assertEqual(fans[0].rpm, 1020)
