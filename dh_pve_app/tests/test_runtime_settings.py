import pytest

from app.runtime_settings import RuntimeSettingError, RuntimeSettings


def test_runtime_settings_accept_valid_value():
    settings = RuntimeSettings()
    value = settings.apply("temperature_publish_delta", "2.5")

    assert value == 2.5
    assert settings.get("temperature_publish_delta") == 2.5


@pytest.mark.parametrize("raw", ["0.1", "11", "nan", "inf", "bad"])
def test_runtime_settings_reject_invalid_or_out_of_range_values(raw):
    settings = RuntimeSettings()

    with pytest.raises(RuntimeSettingError):
        settings.apply("temperature_publish_delta", raw)


def test_runtime_settings_reject_unknown_key():
    settings = RuntimeSettings()

    with pytest.raises(RuntimeSettingError):
        settings.apply("smart_failure_threshold", "1")
