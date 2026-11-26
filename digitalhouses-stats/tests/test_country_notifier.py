"""Pure notifier-state tests: no broker or live database required."""
from datetime import datetime, timezone

import pytest

from digitalhouses_stats.country_notifier import country_name, load_seen, notify_rows


def row(country: str, count: int = 10) -> dict:
    return {
        "country": country,
        "first_seen": datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc),
        "country_count": count,
    }


def test_baseline_does_not_replay_previous_countries(tmp_path) -> None:
    file = tmp_path / "seen.json"
    published = []
    assert notify_rows([row("KZ"), row("US")], file, published.append) == 0
    assert load_seen(file) == {"KZ", "US"}
    assert published == []
    assert notify_rows([row("KZ"), row("US")], file, published.append) == 0


def test_new_country_delivered_once_with_latest_count(tmp_path) -> None:
    file = tmp_path / "seen.json"
    notify_rows([row("KZ")], file, lambda x: None)
    messages = []
    rows = [row("KZ"), row("US", 11)]
    assert notify_rows(rows, file, messages.append) == 1
    assert len(messages) == 1
    assert messages[0]["country"] == "US"
    assert messages[0]["country_name"] == "United States"
    assert messages[0]["country_count"] == 11
    assert messages[0]["first_seen"] == "2026-11-22T01:00:00+00:00"
    assert notify_rows(rows, file, messages.append) == 0
    assert len(messages) == 1


def test_failed_publish_does_not_mark_country_as_sent(tmp_path) -> None:
    file = tmp_path / "seen.json"
    notify_rows([row("KZ")], file, lambda _: None)

    def failure(_):
        raise OSError("broker unavailable")

    with pytest.raises(OSError, match="broker unavailable"):
        notify_rows([row("KZ"), row("ZA")], file, failure)
    assert load_seen(file) == {"KZ"}
    delivered = []
    assert notify_rows([row("KZ"), row("ZA")], file, delivered.append) == 1
    assert delivered[0]["country"] == "ZA"


def test_name_unknown_code_falls_back_to_code() -> None:
    assert country_name("US") == "United States"
    assert country_name("ZA") == "South Africa"
    assert country_name("NOT_A_COUNTRY") == "NOT_A_COUNTRY"
