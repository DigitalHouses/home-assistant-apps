import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_SOURCE = ROOT / "rootfs/app/discovery.py"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
CONFIG = ROOT / "config.yaml"
DOCKERFILE = ROOT / "Dockerfile"


class ReleaseContract014Tests(unittest.TestCase):
    def test_014_release_is_documented(self):
        self.assertIn("## 0.1.14", CHANGELOG.read_text(encoding="utf-8"))
        self.assertIn("DigitalHouses Backblaze App", README.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
