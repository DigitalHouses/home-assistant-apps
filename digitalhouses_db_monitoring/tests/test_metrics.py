import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rootfs' / 'app'))

from metrics import db_depth_days, last_age_seconds, records_k, yesterday_bounds_epoch

class MetricsTests(unittest.TestCase):
    def test_last_age_seconds(self):
        self.assertEqual(last_age_seconds(100.2, 106.9), 6)

    def test_records_k(self):
        self.assertEqual(records_k(12345), 12.3)

    def test_db_depth_uses_local_dates(self):
        tz = ZoneInfo('Asia/Almaty')
        start = datetime(2026, 9, 1, 23, 30, tzinfo=tz).timestamp()
        now = datetime(2026, 9, 4, 0, 10, tzinfo=tz).timestamp()
        self.assertEqual(db_depth_days(start, now, 'Asia/Almaty'), 3)

    def test_yesterday_bounds_are_local_midnight(self):
        tz = ZoneInfo('Asia/Almaty')
        now = datetime(2026, 9, 4, 12, 0, tzinfo=tz).timestamp()
        start, end = yesterday_bounds_epoch(now, 'Asia/Almaty')
        self.assertEqual(datetime.fromtimestamp(start, tz), datetime(2026, 9, 3, 0, 0, tzinfo=tz))
        self.assertEqual(datetime.fromtimestamp(end, tz), datetime(2026, 9, 4, 0, 0, tzinfo=tz))

if __name__ == '__main__':
    unittest.main()

class VersionTests(unittest.TestCase):
    def test_short_postgresql_version(self):
        from metrics import short_db_version
        self.assertEqual(
            short_db_version('PostgreSQL 17.5 (Debian 17.5-1.pgdg120+1) on x86_64-pc-linux-gnu', 'postgresql'),
            'PostgreSQL 17.5',
        )

    def test_short_mariadb_version(self):
        from metrics import short_db_version
        self.assertEqual(
            short_db_version('11.4.5-MariaDB-ubu2404', 'mariadb'),
            'MariaDB 11.4',
        )
