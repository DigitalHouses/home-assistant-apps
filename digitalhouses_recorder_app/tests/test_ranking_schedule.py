import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rootfs' / 'app'))

from rankings import TOP_ENTITIES_24H_INTERVAL_SECONDS, TOP_ENTITIES_ALL_TIME_INTERVAL_SECONDS


class RankingScheduleTests(unittest.TestCase):
    def test_24h_ranking_refreshes_hourly(self):
        self.assertEqual(TOP_ENTITIES_24H_INTERVAL_SECONDS, 3600)

    def test_all_time_ranking_refreshes_daily(self):
        self.assertEqual(TOP_ENTITIES_ALL_TIME_INTERVAL_SECONDS, 86400)


if __name__ == '__main__':
    unittest.main()
