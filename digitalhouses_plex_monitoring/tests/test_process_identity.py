import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from app.models import ProcessSample
from app.process_identity import process_role


def p(name, cmdline):
    return ProcessSample(1, 1.0, name, cmdline, 0.0)


class ProcessIdentityTests(unittest.TestCase):
    def test_real_split_server_argv(self):
        process = p(
            "Plex Media Serv",
            ("/usr/lib/plexmediaserver/Plex", "Media", "Server"),
        )
        self.assertEqual(process_role(process), "server")

    def test_split_scanner_argv(self):
        process = p(
            "Plex Media Scan",
            ("/usr/lib/plexmediaserver/Plex", "Media", "Scanner", "--server-action", "credits"),
        )
        self.assertEqual(process_role(process), "scanner")

    def test_split_transcoder_argv(self):
        process = p(
            "Plex Transcoder",
            ("/usr/lib/plexmediaserver/Plex", "Transcoder"),
        )
        self.assertEqual(process_role(process), "transcoder")

    def test_plugin_and_tuner_are_not_server(self):
        self.assertIsNone(process_role(p(
            "Plex Script Hos",
            ("Plex Plug-in [com.plexapp.system]",),
        )))
        self.assertIsNone(process_role(p(
            "Plex Tuner Service",
            ("/usr/lib/plexmediaserver/Plex Tuner Service",),
        )))


if __name__ == "__main__":
    unittest.main()
