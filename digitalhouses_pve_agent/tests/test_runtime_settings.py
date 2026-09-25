import pytest

from app.runtime_settings import RuntimeSettingError, RuntimeSettings, SETTING_SPECS


EXPECTED = {
    "storage_percent_used_threshold": (80.0, 0.0, 98.0, 1.0, "%", "number.dh_app_pve_storage_percent_used_threshold"),
    "cpu_temperature_threshold": (90.0, 0.0, 110.0, 1.0, "°C", "number.dh_app_pve_cpu_temperature_threshold"),
    "hdd_temperature_threshold": (45.0, 0.0, 70.0, 1.0, "°C", "number.dh_app_pve_hdd_temperature_threshold"),
    "ssd_temperature_threshold": (75.0, 0.0, 90.0, 1.0, "°C", "number.dh_app_pve_ssd_temperature_threshold"),
    "nvme_temperature_threshold": (80.0, 0.0, 110.0, 1.0, "°C", "number.dh_app_pve_nvme_temperature_threshold"),
    "gpu_temperature_threshold": (85.0, 0.0, 110.0, 1.0, "°C", "number.dh_app_pve_gpu_temperature_threshold"),
}


def test_runtime_settings_expose_only_canonical_alert_thresholds():
    assert set(SETTING_SPECS) == set(EXPECTED)
    settings = RuntimeSettings()
    assert settings.as_dict() == {key: values[0] for key, values in EXPECTED.items()}

    for key, expected in EXPECTED.items():
        spec = SETTING_SPECS[key]
        default, minimum, maximum, step, unit, entity_id = expected
        assert (spec.default, spec.minimum, spec.maximum, spec.step, spec.unit, spec.entity_id) == (
            default,
            minimum,
            maximum,
            step,
            unit,
            entity_id,
        )


@pytest.mark.parametrize("key", EXPECTED)
def test_runtime_setting_accepts_inclusive_boundaries_and_zero_is_explicit(key):
    settings = RuntimeSettings()
    _default, minimum, maximum, _step, _unit, _entity_id = EXPECTED[key]

    assert settings.apply(key, str(minimum)) == minimum
    assert settings.get(key) == minimum
    assert settings.apply(key, str(maximum)) == maximum
    assert settings.get(key) == maximum


@pytest.mark.parametrize("key", EXPECTED)
def test_runtime_setting_rejects_out_of_range_values(key):
    settings = RuntimeSettings()
    _default, minimum, maximum, step, _unit, _entity_id = EXPECTED[key]

    with pytest.raises(RuntimeSettingError):
        settings.apply(key, str(minimum - step))
    with pytest.raises(RuntimeSettingError):
        settings.apply(key, str(maximum + step))


@pytest.mark.parametrize("key", EXPECTED)
def test_runtime_setting_rejects_off_step_value(key):
    settings = RuntimeSettings()
    default, _minimum, _maximum, step, _unit, _entity_id = EXPECTED[key]

    with pytest.raises(RuntimeSettingError):
        settings.apply(key, str(default + step / 2.0))


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "NaN", "Infinity"])
def test_runtime_setting_rejects_non_finite_numbers(raw):
    with pytest.raises(RuntimeSettingError):
        RuntimeSettings().apply("cpu_temperature_threshold", raw)


@pytest.mark.parametrize("key", ["fast_poll_interval_seconds", "disk_poll_interval_seconds"])
def test_runtime_settings_reject_removed_poll_interval_controls(key):
    with pytest.raises(RuntimeSettingError):
        RuntimeSettings().apply(key, "20")


def test_runtime_settings_reject_removed_publish_delta_key():
    with pytest.raises(RuntimeSettingError):
        RuntimeSettings().apply("temperature_publish_delta", "2.5")


def test_runtime_settings_ignore_legacy_persisted_controls_on_upgrade():
    settings = RuntimeSettings(
        {
            "fast_poll_interval_seconds": 15.0,
            "disk_poll_interval_seconds": 120.0,
            "cpu_publish_delta": 7.0,
            "temperature_publish_delta": 2.0,
            "cpu_temperature_threshold": 95.0,
        }
    )

    expected = {key: values[0] for key, values in EXPECTED.items()}
    expected["cpu_temperature_threshold"] = 95.0
    assert settings.as_dict() == expected


def test_runtime_settings_reject_unknown_key():
    with pytest.raises(RuntimeSettingError):
        RuntimeSettings().apply("smart_failure_threshold", "1")
