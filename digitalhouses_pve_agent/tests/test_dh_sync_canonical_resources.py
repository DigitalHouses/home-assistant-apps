"""Guard DH Sync PVE/UPS canonical views against CORE v3 dashboard regressions."""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path


PRODUCT = Path(__file__).resolve().parents[1]
DASHBOARDS = PRODUCT / "dashboards" / "ru"
HEADER = (
    "# DH-View: dh_pve_agent\n"
    "# DH-View-Version: 1.0.0\n"
    "# DH-View-Date: 2026-11-14\n"
    "# DH-Compatible-Agent: >=0.5.88,<0.5.90\n"
    "\n"
)
BASELINES = {
    "10_pve_proxmox.yaml": {
        "path": "dh_pve_agent",
        "title": "Proxmox",
        "icon": "mdi:server",
        "sha256": "e41b1f9fe0736f8cf80f31e58214d3e1483200b091f4d8dee086e02e8966626d",
    },
    "11_pve_ups.yaml": {
        "path": "dh_pve_agent_ups",
        "title": "Электропитание",
        "icon": "mdi:power-plug-battery",
        "sha256": "5aef50ab9e4d5db307e1c66a2924a20f38638a77ebd70d06311aa697fd082f96",
    },
}


class DhSyncCanonicalPveResourcesTests(unittest.TestCase):
    def test_only_approved_core_v3_body_changes(self):
        """Reverse approved nav changes and compare with actual read-only CORE snapshots."""
        for filename, expected in BASELINES.items():
            with self.subTest(filename=filename):
                resource = (DASHBOARDS / filename).read_text(encoding="utf-8")
                self.assertTrue(resource.startswith(HEADER))
                body = resource[len(HEADER):]
                self.assertEqual(body.count("show_icon_and_title: false"), 1)
                restored = body.replace(
                    "show_icon_and_title: false\n",
                    "show_icon_and_title: true\n",
                    1,
                )
                if filename == "11_pve_ups.yaml":
                    restored = restored.replace(
                        "icon: mdi:power-plug-battery\n",
                        "icon: mdi:power-plug-battery-outline\n",
                        1,
                    )
                sha256 = hashlib.sha256(restored.encode("utf-8")).hexdigest()
                self.assertEqual(sha256, expected["sha256"])

    def test_standalone_ru_views_and_icon_only_navigation(self):
        paths = set()
        for filename, expected in BASELINES.items():
            with self.subTest(filename=filename):
                text = (DASHBOARDS / filename).read_text(encoding="utf-8")
                # The exact content SHA test anchors the body to known-valid
                # CORE v3 YAML; only inspect top-level scalar keys here. Do
                # not introduce a new PyYAML dependency into Agent runtime/CI.
                view = {}
                for line in text.splitlines():
                    if not line or line[0].isspace() or line.startswith("#"):
                        continue
                    key, separator, value = line.partition(":")
                    if separator:
                        view[key] = value.strip()
                self.assertEqual(view.get("type"), "sections")
                self.assertEqual(view.get("title"), expected["title"])
                self.assertEqual(view.get("path"), expected["path"])
                self.assertEqual(view.get("icon"), expected["icon"])
                self.assertEqual(view.get("show_icon_and_title"), "false")
                self.assertIn("sections", view)
                self.assertNotIn("views", view)
                self.assertNotIn("lovelace", view)
                self.assertNotIn("192.168.11.", text)
                self.assertNotIn(view["path"], paths, "duplicate view path")
                paths.add(view["path"])
        self.assertEqual(paths, {"dh_pve_agent", "dh_pve_agent_ups"})

    def test_narrow_pve_089_source_compatible(self):
        self.assertEqual((PRODUCT / "VERSION").read_text().strip(), "0.5.89")
        for filename in BASELINES:
            text = (DASHBOARDS / filename).read_text(encoding="utf-8")
            self.assertIn("# DH-Compatible-Agent: >=0.5.88,<0.5.90\n", text)
            self.assertNotIn("# DH-Compatible-App:", text)

    def test_confirmed_fan_graph_and_ups_survive(self):
        pve = (DASHBOARDS / "10_pve_proxmox.yaml").read_text(encoding="utf-8")
        ups = (DASHBOARDS / "11_pve_ups.yaml").read_text(encoding="utf-8")
        for marker in (
            "fan_numbers", "rpm_percent", "custom:mini-graph-card",
            "sensor.dh_pve_agent_started", "custom:auto-entities",
        ):
            self.assertIn(marker, pve)
        for marker in ("binary_sensor.dh_pve_agent_ups_configured", "UPS", "sections:"):
            self.assertIn(marker, ups)

    def test_no_placeholder_english_translation(self):
        self.assertFalse((PRODUCT / "dashboards" / "en" / "10_pve_proxmox.yaml").exists())
        self.assertFalse((PRODUCT / "dashboards" / "en" / "11_pve_ups.yaml").exists())
        self.assertTrue((PRODUCT / "docs" / "DH_SYNC_COMPATIBILITY.md").exists())


if __name__ == "__main__":
    unittest.main()
