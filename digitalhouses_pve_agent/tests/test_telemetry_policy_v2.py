"""Mandatory telemetry v2 and critical PVE/UPS upgrade safety."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app import main
from app.config import AppConfig, GeneralConfig, MqttConfig, TelemetryConfig

ROOT = Path(__file__).resolve().parents[1]


def test_explicit_disabled_config_exits_without_starting_any_collectors(monkeypatch, tmp_path, caplog):
    config = AppConfig(
        general=GeneralConfig(instance_id="test_pve", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(host="broker", port=1883, username="", password="",
                        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
                        discovery_prefix="homeassistant", keepalive_seconds=60),
        telemetry=TelemetryConfig(enabled=False),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("no PVE/UPS/MQTT/telemetry work on denied activation")

    monkeypatch.setattr(main, "build_ups_scanner", forbidden)
    monkeypatch.setattr(main, "build_runtime", forbidden)
    monkeypatch.setattr(main, "_telemetry_client", forbidden)
    with caplog.at_level(logging.ERROR):
        assert main.run(config, state_dir=tmp_path) == 0
    assert "Mandatory telemetry disabled" in caplog.text
    assert not (tmp_path / "telemetry.json").exists()


def _preflight_text():
    shell = (ROOT / "install.sh").read_text()
    match = re.search(r"<<'PYTELEMETRY'\n(.*?)\nPYTELEMETRY", shell, re.S)
    assert match, "PVE/UPS upgrade guard must be in installer before mutation"
    assert shell.index("PYTELEMETRY") < shell.index("# On a locally managed UPS")
    return match.group(1)


def _ini(path, enabled=None):
    path.write_text("[mqtt]\nhost = broker\n" + (
        f"[telemetry]\nenabled = {'true' if enabled else 'false'}\n"
        if enabled is not None else ""
    ))


@pytest.mark.parametrize("previous,prepared,allowed", [
    (None, True, True),        # new install defaults ON
    (None, False, False),      # fresh false: unsupported
    (None, None, False),       # missing new field: not allowed
    (False, False, False),    # existing OFF must remain running on its old release
    (False, True, True),      # operator explicitly enabled during upgrade
    (None, True, True),
    (True, True, True),       # preserve previously enabled configuration
])
def test_installer_preflight_protects_running_legacy_pve_ups(tmp_path, previous, prepared, allowed):
    original = tmp_path / 'original.conf'
    target = tmp_path / 'prepared.conf'
    legacy = tmp_path / 'legacy.conf'
    if previous is not None:
        _ini(original, previous)
    _ini(target, prepared)
    before = original.read_bytes() if original.exists() else None
    result = subprocess.run([sys.executable, '-c', _preflight_text(),
                             str(original), str(legacy), str(target)],
                            capture_output=True, text=True)
    assert (result.returncode == 0) is allowed, result.stderr
    assert (original.read_bytes() if original.exists() else None) == before


def test_installer_rejects_unspecified_legacy_without_explicit_new_true(tmp_path):
    original = tmp_path / 'original.conf'
    prepared = tmp_path / 'prepared.conf'
    _ini(original, None)
    _ini(prepared, None)
    result = subprocess.run([sys.executable, '-c', _preflight_text(),
                             str(original), str(tmp_path / 'legacy.conf'), str(prepared)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'original installation unchanged' in result.stderr or 'requires telemetry.enabled=true' in result.stderr
