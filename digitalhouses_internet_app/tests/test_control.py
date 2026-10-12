from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from control import AppCard, ReleaseChecker, latest_release, stable_version


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def opener_for(payload):
    def opener(_request, timeout):
        if timeout != 12:
            raise AssertionError("unexpected timeout")
        return FakeResponse(json.dumps(payload).encode("utf-8"))
    return opener


class ControlTests(unittest.TestCase):
    def test_stable_version(self) -> None:
        self.assertEqual(stable_version("1.2.3"), (1, 2, 3))
        with self.assertRaises(ValueError):
            stable_version("1.2.3-beta")

    def test_latest_release_ignores_other_products_and_unpublished_releases(self) -> None:
        releases = [
            {
                "tag_name": "digitalhouses_internet_app-v0.1.22",
                "published_at": "2026-10-12T18:14:44Z",
                "draft": False,
                "prerelease": False,
            },
            {
                "tag_name": "digitalhouses_internet_app-v0.1.24",
                "published_at": "2026-10-13T00:00:00Z",
                "draft": True,
                "prerelease": False,
            },
            {
                "tag_name": "digitalhouses_plex_agent-v9.9.9",
                "published_at": "2026-10-13T00:00:00Z",
                "draft": False,
                "prerelease": False,
            },
            {
                "tag_name": "digitalhouses_internet_app-v0.1.23",
                "published_at": "2026-10-13T00:01:00Z",
                "draft": False,
                "prerelease": False,
            },
        ]
        tag, version = latest_release(opener=opener_for(releases))
        self.assertEqual(tag, "digitalhouses_internet_app-v0.1.23")
        self.assertEqual(version, "0.1.23")

    def test_release_checker_reports_available_and_error(self) -> None:
        clock_values = iter((10.0, 11.25, 20.0, 21.0))
        checker = ReleaseChecker(
            "0.1.22",
            clock=lambda: next(clock_values),
            now=lambda: "2026-10-13T00:00:00+00:00",
        )
        self.assertTrue(checker.begin())
        ok, error = checker.complete(
            opener=opener_for([
                {
                    "tag_name": "digitalhouses_internet_app-v0.1.23",
                    "published_at": "2026-10-13T00:00:00Z",
                    "draft": False,
                    "prerelease": False,
                }
            ])
        )
        self.assertTrue(ok)
        self.assertIsNone(error)
        payload = checker.payload()
        self.assertEqual(payload["latest_version"], "0.1.23")
        self.assertTrue(payload["available"])
        self.assertEqual(payload["check_duration_seconds"], 1.25)

        self.assertTrue(checker.begin())

        def broken(_request, timeout):
            raise OSError("offline")

        ok, error = checker.complete(opener=broken)
        self.assertFalse(ok)
        self.assertEqual(error, "offline")
        self.assertEqual(checker.payload()["latest_version"], "unknown")
        self.assertIsNone(checker.payload()["available"])

    def test_app_card_runs_and_finishes_operation(self) -> None:
        published = []
        clock_values = iter((100.0, 102.5))
        card = AppCard(
            lambda payload: published.append(payload) is None,
            clock=lambda: next(clock_values),
            now=lambda: "2026-10-13T00:00:00+00:00",
            result_seconds=60,
        )
        self.assertTrue(card.begin("refresh"))
        self.assertEqual(card.payload()["state"], "running")
        self.assertTrue(card.finish("refresh"))
        payload = card.payload()
        self.assertEqual(payload["state"], "success")
        self.assertEqual(payload["duration_seconds"], 2.5)
        self.assertGreaterEqual(len(published), 2)

    def test_app_card_rejects_parallel_operation(self) -> None:
        card = AppCard(lambda _payload: True, result_seconds=60)
        self.assertTrue(card.begin("check"))
        self.assertFalse(card.begin("refresh"))


if __name__ == "__main__":
    unittest.main()
