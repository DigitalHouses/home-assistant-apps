"""No GitHub REST API dependency: real local Git history exercises transport."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from git_source import GitSnapshots, GitSourceError


class LocalGitSnapshots(GitSnapshots):
    def __init__(self, root: Path, origin: Path, **kwargs):
        super().__init__(root, **kwargs)
        self.origin = origin
        self.clone_count = 0

    def _run(self, argv, **kwargs):
        if "clone" in argv:
            self.clone_count += 1
            argv = [str(self.origin) if arg.endswith(
                "https://github.com/DigitalHouses/any-repo.git") else arg
                    for arg in argv]
        return super()._run(argv, **kwargs)


@unittest.skipUnless(shutil.which("git"), "git CLI unavailable")
class GitTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.origin = base / "origin"
        self.origin.mkdir()
        self._git("init", "-b", "main")
        self._git("config", "user.email", "ci@digitalhouses.local")
        self._git("config", "user.name", "DH Sync Test")
        for directory, filename, path in (
            ("product_a", "10_a.yaml", "a"),
            ("product_a", "11_b.yaml", "b"),
            ("product_b", "10_b.yaml", "new"),
        ):
            folder = self.origin / directory / "dashboards/ru"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / filename).write_text(
                f"title: {path}\npath: {path}\ntype: sections\nsections: []\n")
        self._git("add", ".")
        self._git("commit", "-q", "-m", "initial views")
        self.now = [100.]
        self.backend = LocalGitSnapshots(
            base / "cache", self.origin, ttl=300, clock=lambda: self.now[0])
        self.repo = "https://github.com/DigitalHouses/any-repo"

    def _git(self, *argv):
        return subprocess.run(["git", *argv], cwd=self.origin, check=True,
                              text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE).stdout.strip()

    def test_one_clone_for_multiple_products_and_snapshot_sha(self):
        sha, branch = self.backend.resolve_revision(self.repo)
        self.assertEqual(branch, "main")
        self.assertEqual(sha, self._git("rev-parse", "HEAD"))
        a = self.backend.list_views(self.repo, "product_a", sha)
        b = self.backend.list_views(self.repo, "product_b", sha)
        self.assertEqual([x["name"] for x in a],
                         ["10_a.yaml", "11_b.yaml"])
        self.assertEqual([x["name"] for x in b], ["10_b.yaml"])
        self.assertIn(b"path: a\n", self.backend.read_view(
            self.repo, a[0]["path"], sha))
        self.assertEqual(self.backend.clone_count, 1)
        self.assertEqual(self.backend.resolve_revision(self.repo)[0], sha)
        self.assertEqual(self.backend.clone_count, 1)

    def test_absent_optional_dashboard_directory_is_normal(self):
        sha, _ = self.backend.resolve_revision(self.repo)
        self.assertEqual(self.backend.list_views(self.repo, "future_product", sha), [])

    def test_new_commit_refreshes_after_ttl_without_pins(self):
        before, _ = self.backend.resolve_revision(self.repo)
        (self.origin / "product_a/dashboards/ru/12_c.yaml").write_text(
            "title: extra\npath: extra\ntype: masonry\ncards: []\n")
        self._git("add", ".")
        self._git("commit", "-q", "-m", "new product resource")
        self.assertEqual(self.backend.resolve_revision(self.repo)[0], before)
        self.now[0] += 301
        after, _ = self.backend.resolve_revision(self.repo)
        self.assertNotEqual(after, before)
        self.assertEqual(self.backend.clone_count, 2)
        self.assertEqual(len(self.backend.list_views(
            self.repo, "product_a", after)), 3)

    def test_foreign_owner_rejected_before_transport(self):
        with self.assertRaisesRegex(GitSourceError, "DigitalHouses"):
            self.backend.resolve_revision("https://github.com/NotOurOrg/any-repo")
        self.assertEqual(self.backend.clone_count, 0)

    def test_folder_and_path_traversal_rejected(self):
        sha, _ = self.backend.resolve_revision(self.repo)
        with self.assertRaisesRegex(GitSourceError, "Invalid product"):
            self.backend.list_views(self.repo, "../private", sha)
        with self.assertRaisesRegex(GitSourceError, "Unsafe"):
            self.backend.read_view(self.repo, "../secret.yaml", sha)

    def test_root_product_without_dashboards_is_valid(self):
        sha, _ = self.backend.resolve_revision(self.repo)
        self.assertEqual(self.backend.list_views(self.repo, ".", sha), [])


if __name__ == "__main__":
    unittest.main()
