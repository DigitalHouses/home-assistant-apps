import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api_runtime import PlexApiRuntime
from app.config import load_config
from app.plex_api import LibraryInfo, PlexApiError, PlaybackSession


class FakeCollector:
    def __init__(self):
        self.sessions = ()
        self.libraries = ()
        self.fail = False
        self.library_calls = 0
        self.playback_calls = 0

    def collect_playback(self):
        self.playback_calls += 1
        if self.fail:
            raise PlexApiError("boom")
        return self.sessions

    def collect_libraries(self):
        self.library_calls += 1
        if self.fail:
            raise PlexApiError("boom")
        return self.libraries


class PlexApiRuntimeTests(unittest.TestCase):
    def config(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "app.conf"
        path.write_text("[mqtt]\nhost = mqtt\n", encoding="utf-8")
        return load_config(path).plex_api

    def session(self, session_id="s1", content_type="video", bandwidth=1000):
        return PlaybackSession(
            session_id=session_id,
            content_type=content_type,
            media_type="movie" if content_type == "video" else "track",
            title="Title",
            bandwidth_kbps=bandwidth,
            mode="Direct Play",
        )

    def test_first_success_fetches_playback_and_libraries(self):
        collector = FakeCollector()
        collector.sessions = (self.session(),)
        collector.libraries = (
            LibraryInfo("1", "Movies", "movie", "video", 15, movies=15),
        )
        runtime = PlexApiRuntime(self.config(), collector=collector)
        result = runtime.collect(now=100.0)
        self.assertTrue(result.changed)
        self.assertTrue(result.libraries_changed)
        self.assertFalse(result.recovered)
        self.assertFalse(result.failed)
        self.assertEqual(runtime.status, "ok")
        self.assertEqual(collector.library_calls, 1)

    def test_bandwidth_only_change_does_not_trigger_publish(self):
        collector = FakeCollector()
        collector.sessions = (self.session(bandwidth=1000),)
        runtime = PlexApiRuntime(self.config(), collector=collector)
        runtime.collect(now=100.0)
        collector.sessions = (self.session(bandwidth=5000),)
        result = runtime.collect(now=110.0)
        self.assertFalse(result.changed)

    def test_session_change_triggers_publish(self):
        collector = FakeCollector()
        runtime = PlexApiRuntime(self.config(), collector=collector)
        runtime.collect(now=100.0)
        collector.sessions = (self.session(),)
        self.assertTrue(runtime.collect(now=110.0).changed)

    def test_library_refresh_runs_after_scanner_finishes(self):
        collector = FakeCollector()
        runtime = PlexApiRuntime(self.config(), collector=collector)
        runtime.collect(now=100.0)
        self.assertEqual(collector.library_calls, 1)
        runtime.collect(now=110.0)
        self.assertEqual(collector.library_calls, 1)
        runtime.collect(now=120.0, scanner_finished=True)
        self.assertEqual(collector.library_calls, 2)

    def test_failure_keeps_data_but_marks_api_failed(self):
        collector = FakeCollector()
        collector.sessions = (self.session(),)
        runtime = PlexApiRuntime(self.config(), collector=collector)
        runtime.collect(now=100.0)
        collector.fail = True
        result = runtime.collect(now=110.0)
        self.assertTrue(result.changed)
        self.assertTrue(result.failure_transition)
        self.assertTrue(result.failed)
        self.assertEqual(runtime.status, "error")
        self.assertEqual(runtime.last_error, "boom")
        self.assertEqual(len(runtime.sessions), 1)
        collector.fail = False
        recovered = runtime.collect(now=120.0)
        self.assertTrue(recovered.recovered)
        self.assertIsNone(runtime.last_error)


if __name__ == "__main__":
    unittest.main()
