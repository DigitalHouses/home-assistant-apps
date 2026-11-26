import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_build_matrix import build_matrix


class NativeBuildMatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        registry = self.root / "digitalhouses-stats/digitalhouses_stats/product_registry.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(json.dumps({"products": [
            {"id": "test_app", "type": "app"},
            {"id": "test_agent", "type": "agent"},
        ]}))
        self.config = self.root / "test_app/config.yaml"
        self.config.parent.mkdir()
        self.config.write_text("version: 1.0.0\narch:\n  - amd64\n  - aarch64\nstartup: application\n")
        self.app = {"product": "test_app", "version": "1.0.0"}
        self.agent = {"product": "test_agent", "version": "2.0.0"}

    def test_native_architectures(self):
        jobs = build_matrix(self.root, [self.app, self.agent])["include"]
        self.assertEqual([(j["arch"], j["runner"]) for j in jobs],
                         [("amd64", "ubuntu-latest"), ("aarch64", "ubuntu-24.04-arm")])
        self.assertTrue(all(j["version"] == "1.0.0" for j in jobs))

    def test_empty_and_agent_only(self):
        self.assertEqual(build_matrix(self.root, []), {"include": []})
        self.assertEqual(build_matrix(self.root, [self.agent]), {"include": []})

    def test_unsupported_architecture(self):
        self.config.write_text("arch:\n  - armv7\n")
        with self.assertRaises(KeyError):
            build_matrix(self.root, [self.app])

    def test_duplicate_architecture_and_candidate(self):
        with self.assertRaises(ValueError):
            build_matrix(self.root, [self.app, self.app])
        self.config.write_text("arch:\n  - amd64\n  - amd64\n")
        with self.assertRaises(ValueError):
            build_matrix(self.root, [self.app])

    def test_empty_architectures(self):
        self.config.write_text("arch:\nstartup: application\n")
        with self.assertRaises(ValueError):
            build_matrix(self.root, [self.app])


if __name__ == "__main__":
    unittest.main()
