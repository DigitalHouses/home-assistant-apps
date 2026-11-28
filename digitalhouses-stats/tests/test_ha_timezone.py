from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from digitalhouses_stats.ha_timezone import cache_zone, cached_zone, refresh_zone, zone_metadata
from digitalhouses_stats.journal import create_journal
from digitalhouses_stats.dh_journal.http import get


def test_authority_cache_and_fallback(tmp_path):
    settings = SimpleNamespace(journal_path=str(tmp_path / "journal.sqlite3"))
    assert zone_metadata(settings) == {"timezone": "UTC", "timezone_fallback": True}
    assert refresh_zone(settings, lambda: "Europe/Berlin")
    assert cached_zone(settings) == "Europe/Berlin"
    assert not refresh_zone(settings, lambda: "invalid/timezone")
    assert not refresh_zone(settings, lambda: None)
    def unavailable():
        raise OSError("broker down")
    assert not refresh_zone(settings, unavailable)
    assert cached_zone(settings) == "Europe/Berlin"
    assert refresh_zone(settings, lambda: "Asia/Almaty")
    assert cached_zone(settings) == "Asia/Almaty"
    assert refresh_zone(settings, lambda: "UTC")
    assert zone_metadata(settings) == {"timezone": "UTC", "timezone_fallback": False}


def test_journal_utc_history_and_dst(tmp_path):
    settings = SimpleNamespace(journal_path=str(tmp_path / "journal.sqlite3"))
    j = create_journal(settings)
    try:
        j.clock = lambda: datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
        j.info("test", notify=True)
        utc = get(j, "/api/log", cached_zone(settings))[0]
        assert utc["timezone_fallback"]
        cache_zone(settings, "Europe/Berlin")
        local = get(j, "/api/log", cached_zone(settings))[0]
        assert local["rows"][0]["ts"] == utc["rows"][0]["ts"]
        assert local["rows"][0]["local_time"] == "2026-07-01 14:00:00.000"
        assert get(j, "/api/log/toasts?after=0", cached_zone(settings))[0]["rows"][0]["local_time"] == "2026-07-01 14:00:00"
        content, _, filename = get(j, "/api/log/export", cached_zone(settings))
        assert "14-00-00" in filename and b"+02:00" in content
        cache_zone(settings, "Asia/Almaty")
        assert get(j, "/api/log", cached_zone(settings))[0]["rows"][0]["local_time"] == "2026-07-01 17:00:00.000"
    finally:
        j.close()
