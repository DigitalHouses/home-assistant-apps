import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempfile import TemporaryDirectory
import unittest

from app.build_info import BuildInfoError, load_build_info


class BuildInfoTests(unittest.TestCase):
    def test_local_fallback(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
            info = load_build_info(root)
            self.assertEqual(info.version, "0.1.0")
            self.assertEqual(info.source, "local")
            self.assertEqual(info.commit, "unknown")

    def test_installed_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
            (root / "BUILD_INFO").write_text(
                "version = 0.1.0\nsource = main\n"
                "commit = 0123456789abcdef\n",
                encoding="utf-8",
            )
            info = load_build_info(root)
            self.assertEqual(info.source, "main")
            self.assertEqual(info.commit, "0123456789abcdef")

    def test_missing_commit_fails(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
            (root / "BUILD_INFO").write_text(
                "version = 0.1.0\nsource = main\n",
                encoding="utf-8",
            )
            with self.assertRaises(BuildInfoError):
                load_build_info(root)


if __name__ == "__main__":
    unittest.main()
