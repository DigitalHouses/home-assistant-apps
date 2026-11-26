import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_source import source_for, validate_manifest

class ReleaseSourceTests(unittest.TestCase):
    def test_first_parent_source_survives_ci_changes(self):
        head, source, previous = "a"*40, "b"*40, "c"*40
        def git(*args):
            if args[0] == "log":
                return source + "\n" + previous
            if args[0] == "show":
                return "version: " + ("0.1.0" if args[1].startswith(previous) else "0.2.0")
            if args[0] == "rev-parse":
                return "same-tree"
            raise AssertionError(args)
        with patch("release_source.git", side_effect=git):
            self.assertEqual(source_for("test_app", "0.2.0", head), source)

    def test_reject_changed_product_tree(self):
        head, source = "a"*40, "b"*40
        def git(*args):
            if args[0] == "log":
                return source
            if args[0] == "show":
                return "version: 0.2.0"
            if args[0] == "rev-parse":
                return args[1]
            raise AssertionError(args)
        with patch("release_source.git", side_effect=git):
            with self.assertRaisesRegex(ValueError, "without version bump"):
                source_for("test_app", "0.2.0", head)

    def test_manifest_rejects_wrong_revision_or_arch(self):
        source = "a"*40
        doc = {"annotations": {"org.opencontainers.image.revision": source, "org.opencontainers.image.version": "0.2.0"}, "manifests": [{"platform": {"os": "linux", "architecture": "amd64"}}, {"platform": {"os": "unknown", "architecture": "unknown"}}]}
        validate_manifest(doc, source, "0.2.0", "linux/amd64")
        with self.assertRaises(ValueError):
            validate_manifest(doc, "b"*40, "0.2.0", "linux/amd64")
        with self.assertRaises(ValueError):
            validate_manifest(doc, source, "0.2.0", "linux/arm64")

    def test_final_manifest_child_digest_integrity(self):
        source = "a"*40
        amd = "sha256:" + "1"*64
        arm = "sha256:" + "2"*64
        doc = {
            "annotations": {"org.opencontainers.image.revision": source,
                            "org.opencontainers.image.version": "0.2.0",
                            "org.digitalhouses.source-digests": amd + "," + arm},
            "manifests": [
                {"digest": amd, "platform": {"os": "linux", "architecture": "amd64"}},
                {"digest": arm, "platform": {"os": "linux", "architecture": "arm64"}},
                {"digest": "sha256:" + "3"*64,
                 "platform": {"os": "unknown", "architecture": "unknown"}},
            ],
        }
        validate_manifest(doc, source, "0.2.0", "final", amd + "," + arm)
        doc["manifests"][0]["digest"] = "sha256:" + "4"*64
        with self.assertRaisesRegex(ValueError, "child digest mismatch"):
            validate_manifest(doc, source, "0.2.0", "final", amd + "," + arm)
        doc["manifests"][0]["digest"] = amd
        doc["manifests"][0], doc["manifests"][1] = doc["manifests"][1], doc["manifests"][0]
        with self.assertRaisesRegex(ValueError, "platforms"):
            validate_manifest(doc, source, "0.2.0", "final", amd + "," + arm)
