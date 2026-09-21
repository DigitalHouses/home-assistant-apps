from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.gpu_collector import IntelGpuCollector, parse_intel_gpu_top_json, read_gpu_temperature


INTEL_GPU_TOP = r"""
{
  "period": {"duration": 0.020865, "unit": "ms"},
  "frequency": {"requested": 0.0, "actual": 0.0, "unit": "MHz"},
  "rc6": {"value": 0.0, "unit": "%"},
  "engines": {
    "Render/3D/0": {"busy": 0.0},
    "Video/0": {"busy": 0.0},
    "VideoEnhance/0": {"busy": 0.0}
  }
},
{
  "period": {"duration": 1001.858322, "unit": "ms"},
  "frequency": {"requested": 748.608844, "actual": 706.686748, "unit": "MHz"},
  "rc6": {"value": 2.347510, "unit": "%"},
  "engines": {
    "Render/3D/0": {"busy": 77.721573},
    "Video/0": {"busy": 16.355876},
    "VideoEnhance/0": {"busy": 3.54}
  }
}
"""


def test_intel_gpu_top_parser_ignores_short_startup_sample():
    metrics = parse_intel_gpu_top_json(INTEL_GPU_TOP)

    assert metrics["sample_count"] == 1
    assert metrics["video_busy_percent"] == 16.4
    assert metrics["render_busy_percent"] == 77.7
    assert metrics["video_enhance_busy_percent"] == 3.5
    assert metrics["frequency_mhz"] == 706.7
    assert metrics["rc6_percent"] == 2.3


def test_gpu_temperature_uses_hwmon_bound_to_same_pci_device():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        pci = root / "bus/pci/devices/0000:00:10.0"
        pci.mkdir(parents=True)
        hwmon = root / "class/hwmon/hwmon0"
        hwmon.mkdir(parents=True)
        (hwmon / "device").symlink_to(pci)
        (hwmon / "temp1_input").write_text("61500\n", encoding="utf-8")
        (hwmon / "temp2_input").write_text("64300\n", encoding="utf-8")

        assert read_gpu_temperature("0000:00:10.0", sys_root=root) == 64.3


def test_gpu_temperature_is_none_when_guest_exposes_no_hwmon_sensor():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "bus/pci/devices/0000:00:10.0").mkdir(parents=True)
        (root / "class/hwmon").mkdir(parents=True)

        assert read_gpu_temperature("0000:00:10.0", sys_root=root) is None


def test_parser_ignores_incomplete_trailing_sample():
    metrics = parse_intel_gpu_top_json(
        INTEL_GPU_TOP + ',{"period":{"duration":1000},"engines":'
    )

    assert metrics["sample_count"] == 1
    assert metrics["render_busy_percent"] == 77.7


def test_collector_is_fail_soft_without_intel_gpu():
    with patch("app.gpu_collector.detect_intel_gpu_pci", return_value=None):
        payload = IntelGpuCollector().collect()

    assert payload["status"] == "unsupported"
    assert payload["supported"] is False
    assert payload["available"] is False


def test_collector_is_fail_soft_without_intel_gpu_top():
    with (
        patch(
            "app.gpu_collector.detect_intel_gpu_pci",
            return_value="0000:00:10.0",
        ),
        patch("app.gpu_collector.read_gpu_temperature", return_value=None),
        patch("app.gpu_collector.shutil.which", return_value=None),
    ):
        payload = IntelGpuCollector().collect()

    assert payload["status"] == "tool_missing"
    assert payload["supported"] is True
    assert payload["available"] is False


def test_collector_is_fail_soft_when_intel_gpu_top_fails():
    with (
        patch(
            "app.gpu_collector.detect_intel_gpu_pci",
            return_value="0000:00:10.0",
        ),
        patch("app.gpu_collector.read_gpu_temperature", return_value=None),
        patch("app.gpu_collector.shutil.which", return_value="/usr/bin/intel_gpu_top"),
        patch(
            "app.gpu_collector._capture_intel_gpu_top",
            side_effect=RuntimeError("permission denied"),
        ),
    ):
        payload = IntelGpuCollector().collect()

    assert payload["status"] == "error"
    assert payload["supported"] is True
    assert payload["available"] is False
