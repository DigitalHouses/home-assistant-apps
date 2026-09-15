import pytest

from app.runtime_settings import RuntimeSettingError, RuntimeSettings


@pytest.mark.parametrize("key", ["fast_poll_interval_seconds", "disk_poll_interval_seconds"])
def test_runtime_settings_reject_removed_poll_interval_controls(key):
    settings = RuntimeSettings()

    with pytest.raises(RuntimeSettingError):
        settings.apply(key, "20")


def test_runtime_settings_reject_removed_publish_delta_key():
    settings = RuntimeSettings()

    with pytest.raises(RuntimeSettingError):
        settings.apply("temperature_publish_delta", "2.5")


def test_runtime_settings_ignore_legacy_persisted_poll_and_publish_controls_on_upgrade():
    settings = RuntimeSettings(
        {
            "fast_poll_interval_seconds": 15.0,
            "disk_poll_interval_seconds": 120.0,
            "cpu_publish_delta": 7.0,
            "temperature_publish_delta": 2.0,
        }
    )

    assert settings.as_dict() == {}


def test_runtime_settings_have_no_user_configurable_collection_cadence():
    assert RuntimeSettings().as_dict() == {}


def test_runtime_settings_reject_unknown_key():
    settings = RuntimeSettings()

    with pytest.raises(RuntimeSettingError):
        settings.apply("smart_failure_threshold", "1")
