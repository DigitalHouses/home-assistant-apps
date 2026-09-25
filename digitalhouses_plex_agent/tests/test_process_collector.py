import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from app.models import RawProcess
from app.process_collector import CpuSampler, is_plex_process_name


class ProcessCollectorTests(unittest.TestCase):
    def test_plex_name_filter(self):
        for name in (
            "Plex Media Server",
            "Plex Media Scanner",
            "Plex Transcoder",
            "plexmediaserver-helper",
        ):
            self.assertTrue(is_plex_process_name(name), name)
        self.assertFalse(is_plex_process_name("python3"))

    def test_cpu_delta_can_exceed_100(self):
        sampler = CpuSampler()
        first = RawProcess(10, 1.0, "Plex Media Scanner", (), 10.0)
        second = RawProcess(10, 1.0, "Plex Media Scanner", (), 20.6)
        self.assertEqual(sampler.sample([first], 100.0)[0].cpu_percent, 0.0)
        value = sampler.sample([second], 110.0)[0].cpu_percent
        self.assertAlmostEqual(value, 106.0, places=6)

    def test_pid_reuse_is_new_process(self):
        sampler = CpuSampler()
        sampler.sample(
            [RawProcess(10, 1.0, "Plex Media Server", (), 10.0)],
            100.0,
        )
        value = sampler.sample(
            [RawProcess(10, 2.0, "Plex Media Server", (), 99.0)],
            110.0,
        )[0].cpu_percent
        self.assertEqual(value, 0.0)


if __name__ == "__main__":
    unittest.main()
