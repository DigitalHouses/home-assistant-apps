import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from release_candidates import (
    changed_release_candidates,
    pending_existing_release_candidates,
)


class ReleaseCandidatesTests(unittest.TestCase):
    def _run(self, root: Path, *args: str) -> None:
        subprocess.run(
            list(args),
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _write(self, root: Path, path: str, content: str) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _init_repo(self, root: Path) -> None:
        self._run(root, "git", "init", "-q")
        self._run(root, "git", "config", "user.email", "test@example.com")
        self._run(root, "git", "config", "user.name", "Test")

    def _commit_all(self, root: Path, message: str) -> str:
        self._run(root, "git", "add", ".")
        self._run(root, "git", "commit", "-q", "-m", message)
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        return result.stdout.strip()

    def test_detects_only_actual_version_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._init_repo(root)

            self._write(root, "digitalhouses_pve_agent/VERSION", "0.6.0\n")
            self._write(
                root,
                "digitalhouses_recorder_app/config.yaml",
                "name: Recorder\nversion: 0.2.0\noptions:\n  x: 1\n",
            )
            base = self._commit_all(root, "base")

            self._write(root, "digitalhouses_pve_agent/VERSION", "0.6.1\n")
            self._write(
                root,
                "digitalhouses_recorder_app/config.yaml",
                "name: Recorder\nversion: 0.2.0\noptions:\n  x: 2\n",
            )
            head = self._commit_all(root, "change")

            candidates = changed_release_candidates(
                root,
                base=base,
                head=head,
            )

            self.assertEqual(
                [(item.product, item.version) for item in candidates],
                [("digitalhouses_pve_agent", "0.6.1")],
            )

    def test_pending_existing_requires_prior_canonical_tag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._init_repo(root)

            self._write(root, "digitalhouses_pve_agent/VERSION", "0.6.1\n")
            self._write(
                root,
                "digitalhouses_internet_app/config.yaml",
                "name: Internet\nversion: 0.1.3\n",
            )
            self._commit_all(root, "products")
            self._run(root, "git", "tag", "digitalhouses_pve_agent-v0.6.0")

            candidates = pending_existing_release_candidates(root)

            self.assertEqual(
                [(item.product, item.version) for item in candidates],
                [("digitalhouses_pve_agent", "0.6.1")],
            )


    def test_repository_directory_move_is_not_release_intent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._init_repo(root)

            registry_path = (
                "digitalhouses-stats/digitalhouses_stats/product_registry.json"
            )
            base_registry = {
                "schema": 1,
                "products": [
                    {
                        "id": "digitalhouses_pve_agent",
                        "type": "agent",
                        "entity_prefix": "dh_pve_agent_agent",
                        "display_name": "PVE Agent",
                        "telemetry_allowed": True,
                        "release": {
                            "title": "DigitalHouses PVE Agent",
                            "version_source": "version_file",
                            "policy_baseline": "0.5.6",
                        },
                        "repository_directory": "digitalhouses_pve_agent",
                    }
                ],
            }
            self._write(root, "digitalhouses_pve_agent/VERSION", "0.6.0\n")
            self._write(root, registry_path, __import__("json").dumps(base_registry))
            base = self._commit_all(root, "base")

            (root / "digitalhouses_pve_agent").mkdir(parents=True)
            (root / "digitalhouses_pve_agent/VERSION").replace(
                root / "digitalhouses_pve_agent/VERSION"
            )
            (root / "digitalhouses_pve_agent").rmdir()

            head_registry = dict(base_registry)
            head_registry["products"] = [dict(base_registry["products"][0])]
            head_registry["products"][0]["repository_directory"] = (
                "digitalhouses_pve_agent"
            )
            self._write(root, registry_path, __import__("json").dumps(head_registry))
            head = self._commit_all(root, "move")

            candidates = changed_release_candidates(root, base=base, head=head)
            self.assertEqual(candidates, [])

if __name__ == "__main__":
    unittest.main()
