import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.gpu_collector import GpuStateReader


ROOT = Path(__file__).resolve().parents[1]
MAIN_UNIT = (ROOT / "systemd/digitalhouses_plex_monitoring.service").read_text(
    encoding="utf-8"
)
HELPER_UNIT = (ROOT / "systemd/digitalhouses_plex_gpu_helper.service").read_text(
    encoding="utf-8"
)
APP = (ROOT / "app/app.py").read_text(encoding="utf-8")
HELPER = (ROOT / "app/gpu_helper.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "install.sh").read_text(encoding="utf-8")


def test_main_service_does_not_receive_gpu_privilege():
    assert "CAP_SYS_ADMIN" not in MAIN_UNIT
    assert "AmbientCapabilities=" not in MAIN_UNIT
    assert "NoNewPrivileges=true" in MAIN_UNIT


def test_gpu_helper_isolated_capability_contract():
    assert "User=digitalhouses_plex_monitoring" in HELPER_UNIT
    assert "Group=digitalhouses_plex_monitoring" in HELPER_UNIT
    assert "CapabilityBoundingSet=CAP_SYS_ADMIN" in HELPER_UNIT
    assert "AmbientCapabilities=CAP_SYS_ADMIN" in HELPER_UNIT
    assert "NoNewPrivileges=true" in HELPER_UNIT
    assert "ReadWritePaths=/var/lib/digitalhouses_plex_monitoring" in HELPER_UNIT


def test_main_agent_reads_helper_state_instead_of_running_privileged_collector():
    assert "GpuStateReader" in APP
    assert "IntelGpuCollector" not in APP
    assert "IntelGpuCollector" in HELPER
    assert "write_gpu_state_atomic" in HELPER


def test_gpu_state_reader_accepts_fresh_snapshot():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "gpu_state.json"
        path.write_text(
            json.dumps(
                {
                    "collected_at_epoch": 1000.0,
                    "supported": True,
                    "available": True,
                    "status": "ok",
                    "source": "intel_gpu_top",
                    "pci_address": "0000:00:10.0",
                    "video_busy_percent": 21.1,
                    "render_busy_percent": 77.7,
                    "video_enhance_busy_percent": 0.0,
                    "frequency_mhz": 706.7,
                    "rc6_percent": 2.3,
                    "temperature_c": None,
                }
            ),
            encoding="utf-8",
        )

        payload = GpuStateReader(
            path,
            max_age_seconds=30.0,
            now_epoch=lambda: 1010.0,
        ).collect()

    assert payload["status"] == "ok"
    assert payload["available"] is True
    assert payload["video_busy_percent"] == 21.1
    assert "collected_at_epoch" not in payload


def test_gpu_state_reader_rejects_stale_snapshot():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "gpu_state.json"
        path.write_text(
            json.dumps(
                {
                    "collected_at_epoch": 1000.0,
                    "supported": True,
                    "available": True,
                    "status": "ok",
                    "source": "intel_gpu_top",
                    "pci_address": "0000:00:10.0",
                    "video_busy_percent": 90.0,
                    "render_busy_percent": 80.0,
                }
            ),
            encoding="utf-8",
        )

        payload = GpuStateReader(
            path,
            max_age_seconds=30.0,
            now_epoch=lambda: 1040.0,
        ).collect()

    assert payload["status"] == "stale"
    assert payload["available"] is False
    assert payload["video_busy_percent"] is None
    assert payload["render_busy_percent"] is None


def test_installer_manages_gpu_helper_separately():
    assert 'GPU_SERVICE_NAME="digitalhouses_plex_gpu_helper.service"' in INSTALLER
    assert '"${APP_DIR}/systemd/${GPU_SERVICE_NAME}"' in INSTALLER
    assert 'systemctl enable "${GPU_SERVICE_NAME}"' in INSTALLER
    assert 'systemctl restart "${GPU_SERVICE_NAME}"' in INSTALLER
