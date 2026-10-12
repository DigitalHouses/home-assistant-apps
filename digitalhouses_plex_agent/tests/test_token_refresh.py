import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import urllib.error
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import PlexApiConfig
from app.plex_api import PlexApiCollector, PlexApiError
from app import token_refresh


class TokenRefreshTests(unittest.TestCase):
    def test_401_requests_reconciliation_once_per_cooldown(self):
        with TemporaryDirectory() as tmp:
            request = Path(tmp) / "request"
            with patch.object(token_refresh, "_next_request_at", 0.0):
                with patch.object(
                    token_refresh.time, "monotonic", side_effect=[10, 20, 71]
                ):
                    self.assertTrue(token_refresh.request_token_refresh(request))
                    self.assertFalse(token_refresh.request_token_refresh(request))
                    self.assertTrue(token_refresh.request_token_refresh(request))
            self.assertEqual(request.read_text(), "refresh\n")

    def test_reconciliation_is_atomic_and_keeps_restricted_mode(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / ".LocalAdminToken"
            target = Path(tmp) / "plex_local_admin_token"
            source.write_text("new-token\n")
            target.write_text("old-token\n")
            with patch.object(token_refresh.os, "geteuid", return_value=0):
                with patch.object(token_refresh.os, "fchown"):
                    result = token_refresh.sync_token(
                        source, target, group_gid=os.getgid(),
                        validator=lambda token: token == "new-token",
                    )
            self.assertEqual(result, "UPDATED")
            self.assertEqual(target.read_text(), "new-token\n")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),
                             [".LocalAdminToken", "plex_local_admin_token"])

    def test_invalid_replacement_preserves_existing_copy(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / ".LocalAdminToken"
            target = Path(tmp) / "plex_local_admin_token"
            source.write_text("unauthorized")
            target.write_text("last-known")
            with patch.object(token_refresh.os, "geteuid", return_value=0):
                with self.assertRaisesRegex(ValueError, "did not pass"):
                    token_refresh.sync_token(
                        source, target, group_gid=os.getgid(),
                        validator=lambda _token: False,
                    )
            self.assertEqual(target.read_text(), "last-known")

    def test_unchanged_token_is_not_replaced(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            target = Path(tmp) / "target"
            source.write_text("same")
            target.write_text("same\n")
            with patch.object(token_refresh.os, "geteuid", return_value=0):
                result = token_refresh.sync_token(
                    source, target, group_gid=os.getgid(),
                    validator=lambda token: self.fail("must not validate unchanged token"),
                )
            self.assertEqual(result, "UNCHANGED")

    def test_unprivileged_helper_may_not_write_token(self):
        with patch.object(token_refresh.os, "geteuid", return_value=1000):
            with self.assertRaises(PermissionError):
                token_refresh.sync_token()

    def test_401_local_managed_token_requests_sync(self):
        with TemporaryDirectory() as tmp:
            token = Path(tmp) / "token"
            token.write_text("stale-token")
            config = PlexApiConfig(
                enabled=True, base_url="http://127.0.0.1:32400",
                token_file=token, timeout_seconds=3,
                library_refresh_seconds=3600,
            )
            collector = PlexApiCollector(config)
            error = urllib.error.HTTPError(
                "http://127.0.0.1:32400/status/sessions", 401,
                "Unauthorized", {}, None,
            )
            with patch("app.plex_api.AGENT_TOKEN", token):
                with patch("app.plex_api.urllib.request.urlopen", side_effect=error):
                    with patch("app.plex_api.request_token_refresh") as request:
                        with self.assertRaisesRegex(PlexApiError, "401"):
                            collector.collect_playback()
                        request.assert_called_once_with()

    def test_401_to_200_after_reconciliation_without_restarting_collector(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / ".LocalAdminToken"
            token_copy = Path(tmp) / "agent-token"
            request_file = Path(tmp) / "refresh-request"
            source.write_text("new-token\n")
            token_copy.write_text("old-token\n")
            config = PlexApiConfig(
                enabled=True, base_url="http://127.0.0.1:32400",
                token_file=token_copy, timeout_seconds=3,
                library_refresh_seconds=3600,
            )
            collector = PlexApiCollector(config)
            attempts = []

            class Response:
                headers = {}
                def __enter__(self):
                    return self
                def __exit__(self, *_args):
                    return None
                def read(self):
                    return b'<MediaContainer size="0" />'

            def urlopen(req, timeout):
                auth = req.get_header("X-plex-token")
                attempts.append(auth)
                if auth != "new-token":
                    raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
                return Response()

            with patch("app.plex_api.AGENT_TOKEN", token_copy):
                with patch("app.plex_api.urllib.request.urlopen", side_effect=urlopen):
                    with patch(
                        "app.plex_api.request_token_refresh",
                        side_effect=lambda: token_refresh.request_token_refresh(
                            request_file, cooldown_seconds=0.0,
                        ),
                    ):
                        with patch.object(token_refresh, "_next_request_at", 0.0):
                            with self.assertRaisesRegex(PlexApiError, "401"):
                                collector.collect_playback()
                            self.assertTrue(request_file.is_file())
                    with patch.object(token_refresh.os, "geteuid", return_value=0):
                        with patch.object(token_refresh.os, "fchown"):
                            changed = token_refresh.sync_token(
                                source, token_copy, group_gid=os.getgid(),
                                validator=lambda t: t == "new-token",
                            )
                    self.assertEqual(changed, "UPDATED")
                    self.assertEqual(collector.collect_playback(), ())
            self.assertEqual(attempts, ["old-token", "new-token"])

    def test_503_or_custom_token_must_not_trigger_sync(self):
        with TemporaryDirectory() as tmp:
            token = Path(tmp) / "custom-token"
            token.write_text("token")
            config = PlexApiConfig(
                enabled=True, base_url="http://127.0.0.1:32400",
                token_file=token, timeout_seconds=3,
                library_refresh_seconds=3600,
            )
            collector = PlexApiCollector(config)
            with patch("app.plex_api.urllib.request.urlopen", side_effect=urllib.error.HTTPError(
                "http://127.0.0.1:32400/status/sessions", 401,
                "Unauthorized", {}, None,
            )):
                with patch("app.plex_api.request_token_refresh") as request:
                    with self.assertRaises(PlexApiError):
                        collector.collect_playback()
                    request.assert_not_called()

            config = PlexApiConfig(
                enabled=True, base_url="http://127.0.0.1:32400",
                token_file=token, timeout_seconds=3,
                library_refresh_seconds=3600,
            )
            with patch("app.plex_api.AGENT_TOKEN", token):
                with patch("app.plex_api.urllib.request.urlopen", side_effect=urllib.error.HTTPError(
                    "http://127.0.0.1:32400/status/sessions", 503,
                    "Unavailable", {}, None,
                )):
                    with patch("app.plex_api.request_token_refresh") as request:
                        with self.assertRaises(PlexApiError):
                            PlexApiCollector(config).collect_playback()
                        request.assert_not_called()


class InstallerTokenRefreshTests(unittest.TestCase):
    def test_installer_owns_and_enables_refresh_units(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root / "install.sh").read_text()
        watcher = (root / "systemd/digitalhouses_plex_agent_token_refresh.path").read_text()
        helper = (root / "systemd/digitalhouses_plex_agent_token_refresh.service").read_text()
        self.assertIn('systemctl enable --now "${TOKEN_REFRESH_PATH_NAME}"', installer)
        self.assertIn('systemctl disable --now "${TOKEN_REFRESH_PATH_NAME}"', installer)
        self.assertIn("PathModified=/var/lib/digitalhouses_plex_agent/token-refresh-request", watcher)
        self.assertIn("Type=oneshot", helper)
        self.assertIn("ExecStart=/usr/bin/python3 -m app.token_refresh", helper)
        self.assertIn("ReadWritePaths=/etc/digitalhouses_plex_agent", helper)


if __name__ == "__main__":
    unittest.main()
