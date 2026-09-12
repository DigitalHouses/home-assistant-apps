from app.ups_test_history import (
    append_test_history,
    normalize_test_result,
)


def _record(index: int) -> dict[str, object]:
    return {
        "started_at": f"2026-09-{index + 1:02d}T12:00:00+05:00",
        "finished_at": None,
        "type": "Quick",
        "source": "Manual",
        "result": "Started",
        "nut_result": None,
        "duration_seconds": None,
        "battery_charge_before": 100.0,
        "battery_charge_after": None,
        "runtime_before_seconds": 7200.0,
        "runtime_after_seconds": None,
        "load_before_percent": 6.0,
        "failure_reason": None,
    }


def test_normalize_known_nut_battery_test_results():
    assert normalize_test_result("Done and passed") == "Passed"
    assert normalize_test_result("Test in progress") == "Running"
    assert normalize_test_result("Aborted") == "Stopped"
    assert normalize_test_result("Failed") == "Failed"
    assert normalize_test_result(None) == "Unknown"


def test_history_keeps_only_ten_newest_records():
    history: list[dict[str, object]] = []
    for index in range(12):
        history = append_test_history(history, _record(index))

    assert len(history) == 10
    assert history[0]["started_at"] == "2026-09-03T12:00:00+05:00"
    assert history[-1]["started_at"] == "2026-09-12T12:00:00+05:00"


def test_history_copy_does_not_mutate_existing_list():
    original = [_record(0)]
    updated = append_test_history(original, _record(1))

    assert len(original) == 1
    assert len(updated) == 2
