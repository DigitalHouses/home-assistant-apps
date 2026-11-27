import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci_scope import ALL_JOBS, PRODUCT_JOBS, changed_paths, select_jobs


class ScopeTests(unittest.TestCase):
    def test_pve(self):
        self.assertEqual(select_jobs(["digitalhouses_pve_agent/app/main.py"]),
                         {"pve-agent", "sync-app", "stats-server"})

    def test_stats(self):
        self.assertEqual(select_jobs(["digitalhouses-stats/tests/test_api.py"]),
                         {"stats-server"})

    def test_shared_day_night(self):
        for directory in ("digitalhouses_actions_app",
                          "digitalhouses_aqara_switch_app",
                          "digitalhouses_system_globals_app"):
            self.assertEqual(select_jobs([directory + "/config.yaml"]),
                             {"aqara-switch-app", "system-globals-app",
                              "sync-app", "stats-server"})

    def test_shared_and_unknown(self):
        for path in (".github/workflows/validate.yml",
                     "scripts/ci_scope.py", "README.md",
                     "digitalhouses_new_app/config.yaml",
                     "digitalhouses_electrica_app/config.yaml",
                     "digitalhouses-stats/digitalhouses_stats/product_registry.json"):
            self.assertEqual(select_jobs([path]), ALL_JOBS)
        self.assertEqual(select_jobs([]), ALL_JOBS)

    def test_multiple_products(self):
        self.assertEqual(select_jobs(["digitalhouses_plex_agent/VERSION",
                                      "digitalhouses_pbs_agent/VERSION"]),
                         {"plex-agent", "pbs-agent", "sync-app", "stats-server"})

    def test_every_job_mapped(self):
        for directory, job in PRODUCT_JOBS.items():
            self.assertIn(job, select_jobs([directory + "/example"]))

    def test_workflow_scope_matches_mapping(self):
        import yaml
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/validate.yml"
        jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
        scoped = {name for name, job in jobs.items()
                  if job.get("needs") == "validation-scope" and
                  name not in ("repository-contract", "release-readiness")}
        self.assertEqual(scoped, ALL_JOBS)
        for name in scoped:
            self.assertIn(f"\'{name}\'", jobs[name]["if"])

    def test_rename_counts_both_paths(self):
        with patch("ci_scope.subprocess.run") as ancestry, patch(
                "ci_scope.subprocess.check_output",
                return_value=b"digitalhouses_pve_agent/old\x00digitalhouses_pbs_agent/new\x00") as diff:
            paths = changed_paths("base", "head")
            ancestry.assert_called_once()
            self.assertIn("--no-renames", diff.call_args.args[0])
            self.assertTrue({"pve-agent", "pbs-agent"}.issubset(select_jobs(paths)))

    def test_missing_diff_fails(self):
        with patch("ci_scope.subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
            with self.assertRaises(subprocess.CalledProcessError):
                changed_paths("base", "head")


if __name__ == "__main__":
    unittest.main()
