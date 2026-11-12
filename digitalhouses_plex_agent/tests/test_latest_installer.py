"""Contract tests for versionless stable GitHub Release bootstrap."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "install-latest.sh"
BEGIN = "RELEASE_TAG=\"$(python3 - <<'PY'\n"
END = "\nPY\n)\""


def resolver_namespace():
    source = BOOTSTRAP.read_text()
    snippet = source.split(BEGIN, 1)[1].split(END, 1)[0]
    namespace = {"__name__": "unit_test_release_resolver"}
    exec(compile(snippet, str(BOOTSTRAP), "exec"), namespace)
    return namespace


def published(tag, **overrides):
    return dict({"tag_name": tag, "published_at": "2026-11-12T00:00:00Z",
                 "draft": False, "prerelease": False}, **overrides)


class FakeResponse(io.BytesIO):
    def __init__(self, releases):
        super().__init__(json.dumps(releases).encode())


class LatestBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.ns = resolver_namespace()

    def test_only_latest_stable_published_plex_release_selected(self):
        releases = [
            published("digitalhouses_pve_agent-v99.0.0"),
            published("digitalhouses_plex_agent-v0.8.6"),
            published("digitalhouses_plex_agent-v0.8.4"),
            published("digitalhouses_plex_agent-v1.0.0-rc.1"),
            published("digitalhouses_plex_agent-v0.9.9", prerelease=True),
            published("digitalhouses_plex_agent-v0.9.8", draft=True),
            published("digitalhouses_plex_agent-v0.9.7", published_at=None),
            published("digitalhouses_plex_agent-v0.09.2"),
        ]
        requests = []
        def opener(req, timeout):
            requests.append((req.full_url, timeout))
            return FakeResponse(releases)
        self.assertEqual(self.ns["latest_release"](opener=opener),
                         "digitalhouses_plex_agent-v0.8.6")
        self.assertEqual(len(requests), 1)
        self.assertTrue(requests[0][0].endswith("per_page=100&page=1"))
        self.assertEqual(requests[0][1], 12)

    def test_selects_highest_version_across_pages(self):
        calls = []
        def opener(req, timeout):
            calls.append(req.full_url)
            if len(calls) == 1:
                return FakeResponse([published("digitalhouses_pve_agent-v9.9.9")] * 99
                                    + [published("digitalhouses_plex_agent-v0.8.6")])
            return FakeResponse([published("digitalhouses_plex_agent-v0.10.0")])
        self.assertEqual(self.ns["latest_release"](opener=opener),
                         "digitalhouses_plex_agent-v0.10.0")
        self.assertEqual(len(calls), 2)

    def test_no_stable_plex_release_fails_closed(self):
        def opener(req, timeout):
            return FakeResponse([published("digitalhouses_pve_agent-v3.0.0")])
        with self.assertRaisesRegex(ValueError, "No published stable Plex"):
            self.ns["latest_release"](opener=opener)

    def test_unexpected_json_fails_closed(self):
        def opener(req, timeout):
            return FakeResponse({"tag_name": "digitalhouses_plex_agent-v9.0.0"})
        with self.assertRaisesRegex(ValueError, "Unexpected GitHub Releases"):
            self.ns["latest_release"](opener=opener)

    def test_pagination_limit_fails_closed(self):
        calls = []
        def opener(req, timeout):
            calls.append(req.full_url)
            return FakeResponse([published("digitalhouses_plex_agent-v0.8.6")] * 100)
        with self.assertRaisesRegex(ValueError, "pagination exceeded"):
            self.ns["latest_release"](opener=opener)
        self.assertEqual(len(calls), 10)

    def test_shell_bootstrap_runs_installer_from_selected_tag(self):
        source = BOOTSTRAP.read_text()
        # Subprocess test is unprivileged; replace only the root-guard branch in a
        # temporary copy, never alter the production script.
        source = source.replace('if [[ "${EUID}" -ne 0 ]]; then',
                                'if false; then', 1)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bin_dir = base / "bin"
            bin_dir.mkdir()
            fake_python = bin_dir / "python3"
            fake_python.write_text(
                "#!/bin/sh\necho digitalhouses_plex_agent-v0.8.6\n"
            )
            fake_python.chmod(0o755)
            fake_curl = bin_dir / "curl"
            fake_curl.write_text("""#!/bin/sh
out=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then
    shift
    out="$1"
  else
    case "$1" in https://*) printf '%s' "$1" > "$FETCHED_URL" ;; esac
  fi
  shift
done
printf '#!/usr/bin/env bash\\nprintf "installed-from=%%s\\\\n" "$DIGITALHOUSES_SOURCE_REF"\\n' > "$out"
""")
            fake_curl.chmod(0o755)
            runfile = base / "bootstrap.sh"
            runfile.write_text(source)
            url_log = base / "fetch-url"
            env = dict(os.environ, PATH=str(bin_dir) + ":" + os.environ["PATH"],
                       FETCHED_URL=str(url_log))
            result = subprocess.run(["bash", str(runfile)], capture_output=True,
                                    text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Latest stable Plex Agent release: digitalhouses_plex_agent-v0.8.6",
                          result.stdout)
            self.assertIn("installed-from=digitalhouses_plex_agent-v0.8.6",
                          result.stdout)
            self.assertEqual(url_log.read_text(),
                             "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/"
                             "digitalhouses_plex_agent-v0.8.6/digitalhouses_plex_agent/install.sh")


if __name__ == "__main__":
    unittest.main()
