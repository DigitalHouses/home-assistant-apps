import pytest

from app.runtime_settings import RuntimeSettingError, RuntimeSettings


def test_runtime_settings_accept_valid_poll_interval():
    settings = RuntimeSettings()
    value = settings.apply("fast_poll_interval_seconds", "20")

    assert value == 20.0
    assert settings.get("fast_poll_interval_seconds") == 20.0


@pytest.mark.parametrize("raw", ["1", "61", "nan", "inf", "bad"])
def test_runtime_settings_reject_invalid_or_out_of_range_values(raw):
    settings = RuntimeSettings()

    with pytest.raises(RuntimeSettingError):
        settings.apply("fast_poll_interval_seconds", raw)


def test_runtime_settings_reject_removed_publish_delta_key():
    settings = RuntimeSettings()

    with pytest.raises(RuntimeSettingError):
        settings.apply("temperature_publish_delta", "2.5")


def test_runtime_settings_ignore_legacy_persisted_publish_deltas_on_upgrade():
    settings = RuntimeSettings(
        {
            "fast_poll_interval_seconds": 15.0,
            "cpu_publish_delta": 7.0,
            "temperature_publish_delta": 2.0,
        }
    )

    assert settings.as_dict() == {
        "fast_poll_interval_seconds": 15.0,
        "disk_poll_interval_seconds": 60.0,
    }


def test_runtime_settings_reject_unknown_key():
    settings = RuntimeSettings()

    with pytest.raises(RuntimeSettingError):
        settings.apply("smart_failure_threshold", "1")
