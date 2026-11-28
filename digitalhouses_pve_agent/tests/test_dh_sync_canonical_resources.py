"""Guard DH Sync PVE/UPS canonical views against approved dashboard regressions."""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path


PRODUCT = Path(__file__).resolve().parents[1]
DASHBOARDS = PRODUCT / "dashboards" / "ru"
HEADERS = {
    "10_pve_proxmox.yaml": (
        "# DH-View: dh_pve_agent\n"
        "# DH-View-Version: 1.0.2\n"
        "# DH-View-Date: 2026-11-22\n"
        "\n"
    ),
    "11_pve_ups.yaml": (
        "# DH-View: dh_pve_agent\n"
        "# DH-View-Version: 1.0.1\n"
        "# DH-View-Date: 2026-11-24\n"
        "\n"
    ),
}
AUTO_UPDATE_CARD = (
    "      - type: custom:mushroom-entity-card\n"
    "        entity: switch.dh_pve_agent_auto_update\n"
    "        name: Автообновление PVE Agent\n"
    "        icon: mdi:autorenew\n"
    "        primary_info: name\n"
    "        secondary_info: state\n"
    "        tap_action:\n"
    "          action: toggle\n"
    "        hold_action:\n"
    "          action: more-info\n"
    "        grid_options:\n"
    "          columns: 12\n"
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
        "sha256": "bab67c7fd21b2b490c3f3476020d3345598e40458cdbd8e363ca38a3545e7279",
    },
}


class DhSyncCanonicalPveResourcesTests(unittest.TestCase):
    def test_only_approved_core_v3_body_changes(self):
        """Protect accepted PVE v3 and approved UPS v1.0.1 body from regressions."""
        for filename, expected in BASELINES.items():
            with self.subTest(filename=filename):
                resource = (DASHBOARDS / filename).read_text(encoding="utf-8")
                header = HEADERS[filename]
                self.assertTrue(resource.startswith(header))
                body = resource[len(header):]
                if filename == "10_pve_proxmox.yaml":
                    # Undo the approved additive backup history card before
                    # comparing the previously accepted CORE v3 dashboard.
                    start = body.index("      - type: heading\n        heading: Резервное копирование PVE\n")
                    end = body.index("      - type: markdown\n        title: PVE · События памяти", start)
                    backup_fragment = body[start:end]
                    self.assertIn("number.dh_pve_agent_backup_history_limit", backup_fragment)
                    self.assertIn("<details", backup_fragment)
                    body = body[:start] + body[end:]
                    # Remove only the two explicitly approved additive CPU charts.
                    title = body.index("        title: Структура CPU · 24 часа\n")
                    start = body.rindex("      - type: statistics-graph\n", 0, title)
                    end = body.index("      - type: heading\n        heading: Частота CPU · 24 часа\n", title)
                    fragment = body[start:end]
                    self.assertEqual(fragment.count("type: statistics-graph"), 2)
                    self.assertEqual(fragment.count("condition: numeric_state"), 2)
                    for name in ("user", "system", "guest", "iowait", "irq", "idle"):
                        self.assertEqual(fragment.count(f"- entity: sensor.dh_pve_agent_cpu_{name}\n"), 2)
                    body = body[:start] + body[end:]
                    # Preserve the exact v3 CORE baseline except for the
                    # intentional, narrowly scoped Diagnostics UI update.
                    self.assertEqual(body.count("        heading: Диагностика\n"), 1)
                    self.assertEqual(body.count(AUTO_UPDATE_CARD), 1)
                    body = body.replace(
                        "        heading: Диагностика\n",
                        "        heading: Приложение\n",
                        1,
                    ).replace(AUTO_UPDATE_CARD, "", 1)
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

    def test_owner_only_no_agent_version_range(self):
        for filename in BASELINES:
            text = (DASHBOARDS / filename).read_text(encoding="utf-8")
            self.assertNotIn("# DH-Compatible-", text)

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

    def test_proxmox_diagnostics_exposes_existing_auto_update_switch(self):
        pve = (DASHBOARDS / "10_pve_proxmox.yaml").read_text(encoding="utf-8")
        self.assertEqual(pve.count("switch.dh_pve_agent_auto_update"), 1)
        self.assertIn(AUTO_UPDATE_CARD, pve)
        self.assertLess(
            pve.index("        heading: Диагностика"),
            pve.index(AUTO_UPDATE_CARD),
        )
        self.assertIn("action: toggle", AUTO_UPDATE_CARD)
        self.assertIn("secondary_info: state", AUTO_UPDATE_CARD)
        # Existing MQTT switch owns state and command; no extra entity or
        # custom scripts are required for the canonical DH Sync view.
        from app.discovery import build_discovery_payload
        from app.config import AppConfig, GeneralConfig, MqttConfig
        from app.identity import HostIdentity
        config = AppConfig(
            general=GeneralConfig(instance_id="pve_test", node_name="PVE", log_level="info"),
            mqtt=MqttConfig(host="mqtt", port=1883, username="", password="",
                            topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
                            discovery_prefix="homeassistant", keepalive_seconds=60),
        )
        identity = HostIdentity(
            machine_id="0123456789abcdef0123456789abcdef",
            instance_id="pve_test", hostname="pve", node_name="PVE",
        )
        switch = build_discovery_payload(config, identity, version="0.5.93")["components"]["auto_update"]
        self.assertEqual(switch["platform"], "switch")
        self.assertEqual(switch["default_entity_id"], "switch.dh_pve_agent_auto_update")
        self.assertTrue(switch["command_topic"].endswith("/update/auto/set"))
        self.assertEqual(switch["state_topic"].split("/")[-1], "state")

    def test_no_placeholder_english_translation(self):
        self.assertFalse((PRODUCT / "dashboards" / "en" / "10_pve_proxmox.yaml").exists())
        self.assertFalse((PRODUCT / "dashboards" / "en" / "11_pve_ups.yaml").exists())
        self.assertTrue((PRODUCT / "docs" / "DH_SYNC_COMPATIBILITY.md").exists())


if __name__ == "__main__":
    unittest.main()
