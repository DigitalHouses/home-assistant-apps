import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from app.metrics import RollingCpuMetrics, group_current_cpu
from app.models import ProcessSample


class MetricsTests(unittest.TestCase):
    def test_grouping(self):
        processes = [
            ProcessSample(1, 1, "Plex Media Server", (), 20),
            ProcessSample(2, 1, "Plex Media Scanner", (), 106),
            ProcessSample(3, 1, "Plex Transcoder", (), 40),
            ProcessSample(4, 1, "python3", (), 90),
        ]
        self.assertEqual(group_current_cpu(processes), (166.0, 106.0, 40.0))

    def test_rolling_average_and_max(self):
        metrics = RollingCpuMetrics(60)
        metrics.update(0, 0, 0, 0)
        metrics.update(10, 100, 60, 0)
        current = metrics.update(20, 50, 30, 10)
        self.assertEqual(current.total.current, 50)
        self.assertEqual(current.total.average, 50)
        self.assertEqual(current.total.maximum, 100)

        at_70 = metrics.update(70, 10, 5, 0)
        # t=0 is evicted; t=10 stays because cutoff is 10.
        self.assertAlmostEqual(at_70.total.average, (100 + 50 + 10) / 3)


if __name__ == "__main__":
    unittest.main()
