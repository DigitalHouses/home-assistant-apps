from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
from app.collectors.smart import parse_smart_json
from app.daily_disk_stats import update_daily_stats

FIX = Path(__file__).parent / "fixtures" / "disks"


def nvme():
    return parse_smart_json(json.loads((FIX / "nvme_samsung_990_evo.json").read_text()), "/dev/nvme0")


def test_daily_stats_keep_max_temperature_and_latest_lifetime_counters():
    s = nvme()
    current, completed = update_daily_stats(None, replace(s, temperature_c=57), datetime.fromisoformat("2026-09-10T10:00:00+05:00"))
    assert completed is None
    current, completed = update_daily_stats(current, replace(s, temperature_c=67, power_on_hours=8939), datetime.fromisoformat("2026-09-10T18:00:00+05:00"))
    assert completed is None
    assert current.max_temperature_c == 67.0
    assert current.power_on_hours == 8939
    assert current.wear_used_percent == 3.0


def test_day_rollover_returns_completed_previous_day():
    s = nvme()
    current, _ = update_daily_stats(None, s, datetime.fromisoformat("2026-09-10T23:59:00+05:00"))
    new_current, completed = update_daily_stats(current, replace(s, temperature_c=55), datetime.fromisoformat("2026-09-11T00:01:00+05:00"))
    assert completed.day == "2026-09-10"
    assert new_current.day == "2026-09-11"
    assert new_current.max_temperature_c == 55.0
