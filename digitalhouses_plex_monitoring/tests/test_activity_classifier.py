import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from app.activity_classifier import (
    classify_activity,
    extract_current_item,
    extract_server_actions,
)
from app.models import ProcessSample


def p(name: str, cmdline: tuple[str, ...] = ()) -> ProcessSample:
    return ProcessSample(1, 1.0, name, cmdline, 0.0)


class ActivityClassifierTests(unittest.TestCase):
    def test_credits_observed_style(self):
        state = classify_activity([
            p("Plex Media Server"),
            p(
                "Plex Media Scanner",
                (
                    "Plex Media Scanner",
                    "--log-file-suffix",
                    "Credits",
                    "--creditsTempDataPath",
                    "/tmp/PlexCreditsDetection-123",
                    "/media/Mazhor.s2.01.HDTV1080.ts",
                ),
            ),
        ])
        self.assertTrue(state.credits_detection)
        self.assertEqual(state.activity, "credits_detection")
        self.assertEqual(state.current_item, "Mazhor.s2.01.HDTV1080.ts")

    def test_combined_server_actions(self):
        cmd = (
            "Plex Media Scanner",
            "--server-action",
            "index,intro,credits,voiceActivity",
        )
        self.assertEqual(
            extract_server_actions(cmd),
            ("index", "intro", "credits", "voiceactivity"),
        )
        state = classify_activity([
            p("Plex Media Server"),
            p("Plex Media Scanner", cmd),
        ])
        self.assertTrue(state.credits_detection)
        self.assertTrue(state.intro_detection)
        self.assertTrue(state.thumbnail_generation)
        self.assertEqual(state.activity, "multiple")

    def test_intros_variant(self):
        state = classify_activity([
            p("Plex Media Server"),
            p(
                "Plex Media Scanner",
                ("Plex Media Scanner", "--server-action", "intros"),
            ),
        ])
        self.assertTrue(state.intro_detection)

    def test_plain_generate_is_generic_scanner(self):
        state = classify_activity([
            p("Plex Media Server"),
            p(
                "Plex Media Scanner",
                ("Plex Media Scanner", "--generate", "--section", "2"),
            ),
        ])
        self.assertTrue(state.scanner_running)
        self.assertFalse(state.thumbnail_generation)
        self.assertEqual(state.activity, "scanner")

    def test_chapter_thumbs_is_thumbnail(self):
        state = classify_activity([
            p("Plex Media Server"),
            p(
                "Plex Media Scanner",
                ("Plex Media Scanner", "--chapter-thumbs-only"),
            ),
        ])
        self.assertTrue(state.thumbnail_generation)

    def test_filename_containing_credits_is_not_a_credits_signature(self):
        state = classify_activity([
            p("Plex Media Server"),
            p(
                "Plex Media Scanner",
                ("Plex Media Scanner", "/media/movie_credits.mkv"),
            ),
        ])
        self.assertFalse(state.credits_detection)
        self.assertEqual(state.activity, "scanner")

    def test_unknown_server_actions_remain_visible(self):
        state = classify_activity([
            p("Plex Media Server"),
            p(
                "Plex Media Scanner",
                (
                    "Plex Media Scanner",
                    "--server-action",
                    "voiceActivity,addetect",
                ),
            ),
        ])
        self.assertEqual(
            state.scanner_actions,
            ("voiceactivity", "addetect"),
        )
        self.assertEqual(state.activity, "scanner")

    def test_transcoder_plus_scanner_is_multiple(self):
        state = classify_activity([
            p("Plex Media Server"),
            p("Plex Media Scanner"),
            p("Plex Transcoder"),
        ])
        self.assertTrue(state.transcoder_running)
        self.assertTrue(state.scanner_running)
        self.assertEqual(state.activity, "multiple")

    def test_server_only_idle(self):
        self.assertEqual(
            classify_activity([p("Plex Media Server")]).activity,
            "idle",
        )

    def test_no_plex_processes(self):
        self.assertEqual(classify_activity([]).activity, "plex_not_running")

    def test_transcoder_input_file_beats_output_format(self):
        cmd = (
            "/usr/lib/plexmediaserver/Plex Transcoder",
            "-i",
            "/mnt/truenas/data/plex/movies/X-Men. The Last Stand (2006) 4K.mkv",
            "-f",
            "dash",
            "dash",
        )
        self.assertEqual(
            extract_current_item(cmd),
            "X-Men. The Last Stand (2006) 4K.mkv",
        )

    def test_internal_item_ids_are_not_current_items(self):
        self.assertIsNone(
            extract_current_item(("Plex Media Scanner", "--item", "30"))
        )
        self.assertIsNone(
            extract_current_item(("Plex Media Scanner", "--section", "5"))
        )

    def test_parallel_transcoders_are_exposed(self):
        state = classify_activity([
            p("Plex Media Server"),
            p(
                "Plex Transcoder",
                (
                    "/usr/lib/plexmediaserver/Plex Transcoder",
                    "-i",
                    "/media/X-Men.mkv",
                    "-f",
                    "dash",
                ),
            ),
            p(
                "Plex Transcoder",
                (
                    "/usr/lib/plexmediaserver/Plex Transcoder",
                    "-i",
                    "/media/Avatar.mkv",
                    "-f",
                    "ssegment",
                ),
            ),
        ])
        self.assertEqual(state.activity, "transcoding")
        self.assertEqual(
            getattr(state, "current_items", None),
            ("X-Men.mkv", "Avatar.mkv"),
        )
        self.assertEqual(getattr(state, "transcoder_count", None), 2)
        self.assertEqual(getattr(state, "scanner_count", None), 0)


if __name__ == "__main__":
    unittest.main()
