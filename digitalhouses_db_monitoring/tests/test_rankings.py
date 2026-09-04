import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rootfs' / 'app'))

from rankings import build_top_entities_snapshot


class RankingSnapshotTests(unittest.TestCase):
    def test_snapshot_contains_top_10_and_local_generation_time(self):
        rows = [
            ('sensor.alpha', 120),
            ('binary_sensor.beta', 80),
        ]
        generated = datetime.fromisoformat('2026-09-05T03:15:00+05:00').timestamp()

        snapshot = build_top_entities_snapshot(rows, '24h', generated, 'Asia/Almaty')

        self.assertEqual(snapshot['top_entity'], 'sensor.alpha')
        self.assertEqual(snapshot['top_records'], 120)
        self.assertEqual(snapshot['period'], '24h')
        self.assertEqual(snapshot['generated_at'], '2026-09-05T03:15:00+05:00')
        self.assertEqual(snapshot['top_10'], [
            {'entity_id': 'sensor.alpha', 'records': 120},
            {'entity_id': 'binary_sensor.beta', 'records': 80},
        ])

    def test_empty_snapshot_has_zero_state_and_no_top_entity(self):
        generated = datetime.fromisoformat('2026-09-05T03:15:00+05:00').timestamp()

        snapshot = build_top_entities_snapshot([], 'all_time', generated, 'Asia/Almaty')

        self.assertIsNone(snapshot['top_entity'])
        self.assertEqual(snapshot['top_records'], 0)
        self.assertEqual(snapshot['top_10'], [])
        self.assertEqual(snapshot['period'], 'all_time')


if __name__ == '__main__':
    unittest.main()
