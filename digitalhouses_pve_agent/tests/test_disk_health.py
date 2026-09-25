from dataclasses import replace
import json
from pathlib import Path
from app.collectors.smart import parse_smart_json
from app.disk_health import evaluate_disk_health, DiskHealthState

FIX = Path(__file__).parent / "fixtures" / "disks"


def nvme():
    return parse_smart_json(json.loads((FIX / "nvme_samsung_990_evo.json").read_text()), "/dev/nvme0")


def test_real_nvme_is_healthy():
    result = evaluate_disk_health(nvme())
    assert result.state is DiskHealthState.HEALTHY
    assert result.reasons == ()


def test_wear_thresholds_are_built_in():
    warning = evaluate_disk_health(replace(nvme(), wear_used_percent=70))
    critical = evaluate_disk_health(replace(nvme(), wear_used_percent=90))
    assert warning.state is DiskHealthState.WARNING
    assert "wearout" in warning.reasons
    assert warning.recommendation == "Запланировать замену диска"
    assert critical.state is DiskHealthState.CRITICAL


def test_existing_media_error_is_warning_but_growth_is_critical():
    current = replace(nvme(), media_errors=1)
    assert evaluate_disk_health(current).state is DiskHealthState.WARNING
    assert evaluate_disk_health(current, previous={"media_errors": 0}).state is DiskHealthState.CRITICAL


def test_smart_failure_or_nvme_critical_warning_is_critical():
    assert evaluate_disk_health(replace(nvme(), smart_passed=False)).state is DiskHealthState.CRITICAL
    assert evaluate_disk_health(replace(nvme(), critical_warning=1)).state is DiskHealthState.CRITICAL


def test_unsafe_shutdown_growth_is_warning_not_disk_failure():
    current = replace(nvme(), unsafe_shutdowns=26)
    result = evaluate_disk_health(current, previous={"unsafe_shutdowns": 25})
    assert result.state is DiskHealthState.WARNING
    assert "unsafe_shutdown_growth" in result.reasons
    assert "питание" in result.recommendation.lower()
