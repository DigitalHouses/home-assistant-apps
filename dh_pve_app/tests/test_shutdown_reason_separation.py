from app.shutdown_history import classify_previous_shutdown


def test_unclean_shutdown_result_does_not_become_shutdown_reason():
    shutdown_class, shutdown_reason = classify_previous_shutdown(
        clean_shutdown=False,
        fsd_reason=None,
    )

    assert shutdown_class == "unclean"
    assert shutdown_reason == "unknown"


def test_missing_shutdown_result_does_not_become_shutdown_reason():
    shutdown_class, shutdown_reason = classify_previous_shutdown(
        clean_shutdown=None,
        fsd_reason=None,
    )

    assert shutdown_class == "unknown"
    assert shutdown_reason == "unknown"


def test_known_ups_reason_is_preserved_independently_of_shutdown_result():
    for clean_shutdown in (True, False, None):
        shutdown_class, shutdown_reason = classify_previous_shutdown(
            clean_shutdown=clean_shutdown,
            fsd_reason="on_battery_fsd",
        )

        assert shutdown_class == "ups_power"
        assert shutdown_reason == "on_battery_fsd"
