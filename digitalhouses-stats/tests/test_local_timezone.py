from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from digitalhouses_stats import local_timezone
from digitalhouses_stats.journal import create_journal
from digitalhouses_stats.dh_journal.http import get


def test_system_timezone_and_history(tmp_path, monkeypatch):
    link = tmp_path / "localtime"
    monkeypatch.setattr(local_timezone, "LOCALTIME", link)
    assert local_timezone.zone_metadata() == {"timezone": "UTC", "timezone_fallback": True}
    settings = SimpleNamespace(journal_path=str(tmp_path / "journal.sqlite3"))
    j = create_journal(settings)
    try:
        j.clock = lambda: datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
        j.info("test", notify=True)
        utc = get(j, "/api/log", local_timezone.local_zone())[0]
        assert utc["timezone_fallback"]
        link.symlink_to(Path("/usr/share/zoneinfo/Europe/Berlin"))
        assert local_timezone.local_zone() == "Europe/Berlin"
        local = get(j, "/api/log", local_timezone.local_zone())[0]
        assert local["rows"][0]["ts"] == utc["rows"][0]["ts"]
        assert local["rows"][0]["local_time"] == "2026-07-01 14:00:00.000"
        link.unlink()
        link.symlink_to(Path("/usr/share/zoneinfo/Asia/Almaty"))
        assert local_timezone.zone_metadata() == {"timezone": "Asia/Almaty", "timezone_fallback": False}
        data = get(j, "/api/log", local_timezone.local_zone())[0]
        assert data["rows"][0]["local_time"] == "2026-07-01 17:00:00.000"
        assert data["rows"][0]["ts"] == utc["rows"][0]["ts"]
        assert get(j, "/api/log/toasts?after=0", local_timezone.local_zone())[0]["rows"][0]["local_time"] == "2026-07-01 17:00:00"
        content, _, filename = get(j, "/api/log/export", local_timezone.local_zone())
        assert "17-00-00" in filename and b"+05:00" in content
    finally:
        j.close()
