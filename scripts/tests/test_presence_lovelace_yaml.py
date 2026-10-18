"""Parse the maintained Presence Lovelace YAML and validate its button-card structure.

Lives in repository-contract tests because PyYAML is installed in that CI job.
The Presence runtime unit test job intentionally does not depend on PyYAML.
"""
import unittest
from pathlib import Path
from datetime import datetime

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2] / "digitalhouses_presence_app"
CARD = ROOT / "examples/lovelace/presence_app_card_ru.yaml"
DASH = ROOT / "examples/lovelace/dh_presence_app_dashboard.yaml"
GPS_SOURCES = ROOT / "examples/lovelace/presence_gps_trackers_auto_entities_ru.yaml"
WIFI_SOURCES = ROOT / "examples/lovelace/presence_wifi_trackers_auto_entities_ru.yaml"
ZONE_COUNTS = ROOT / "examples/lovelace/presence_zones_auto_entities_ru.yaml"
REGISTERED = ROOT / "examples/lovelace/presence_registered_phones_markdown_ru.yaml"
RECENT = ROOT / "examples/lovelace/presence_recent_events_markdown_ru.yaml"


class PresenceLovelaceYamlTests(unittest.TestCase):
    def test_portable_auto_entities_use_live_registered_roster_only(self):
        for path, field in ((GPS_SOURCES, "gps_tracker"),
                            (WIFI_SOURCES, "wifi_tracker")):
            with self.subTest(card=path.name):
                text = path.read_text(encoding="utf-8")
                config = yaml.safe_load(text)
                self.assertEqual(config["type"], "custom:auto-entities")
                self.assertEqual(config["card"]["type"], "entities")
                self.assertEqual(config["sort"]["method"], "name")
                self.assertTrue(config["unique"])
                self.assertFalse(config["show_empty"])
                self.assertNotIn("device_tracker.", text)
                self.assertNotIn("tojson", text)
                self.assertEqual(set(config["filter"]), {"template"})
                source = config["filter"]["template"]
                self.assertIn("state_attr('binary_sensor.dh_presence_app_residents_home', 'residents')",
                              source)
                self.assertIn("map(attribute='" + field + "')", source)

    def test_portable_source_templates_work_in_different_homes(self):
        # Execute the actual Lovelace Jinja with a fake HA state_attr.
        env = Environment()
        cases = [
            {
                "alfa": {"gps_tracker": "device_tracker.alfa_ios",
                         "wifi_tracker": "device_tracker.controller_alfa"},
                "bravo": {"gps_tracker": "device_tracker.bravo_android",
                          "wifi_tracker": "device_tracker.router_bravo"},
                "unlinked": {"gps_tracker": "device_tracker.tablet", "wifi_tracker": None},
            },
            {
                "home_one": {"gps_tracker": "device_tracker.somebody_mobile",
                             "wifi_tracker": "device_tracker.ap_67"},
            },
            {},
        ]
        for roster in cases:
            for path, field in ((GPS_SOURCES, "gps_tracker"),
                                (WIFI_SOURCES, "wifi_tracker")):
                with self.subTest(roster=roster, card=path.name):
                    template = yaml.safe_load(path.read_text(encoding="utf-8"))["filter"]["template"]
                    actual = env.from_string(template).render(
                        state_attr=lambda entity, attr: roster).strip()
                    expected = ", ".join(r[field] for r in roster.values()
                                         if r.get(field))
                    self.assertEqual(actual, expected)
                    self.assertNotIn("None", actual)

    def test_presence_markdown_pve_tree_and_events_table(self):
        """Reuse the PVE dashboard's monospace tree and compact Markdown table."""
        dashboard = yaml.safe_load(DASH.read_text(encoding="utf-8"))
        residents = dashboard["sections"][1]["cards"]
        notifications = dashboard["sections"][2]["cards"]
        cards = (
            (REGISTERED, residents[1]),
            (RECENT, notifications[3]),
        )
        env = Environment()
        roster = {
            "one": {"registered": True, "registration_label": "Serzhan (iPhone)",
                    "gps_tracker": "device_tracker.phone_1",
                    "wifi_tracker": "device_tracker.router_1"},
            "two": {"registered": True, "registration_label": "Alina (iPhone)",
                    "gps_tracker": "device_tracker.phone_2", "wifi_tracker": None},
            "old": {"registered": False, "registration_label": None,
                    "gps_tracker": "device_tracker.legacy",
                    "wifi_tracker": None},
        }
        event_rows = [
            {"title": "GPS: дома", "details": "Serzhan (iPhone)",
             "timestamp": "2026-10-18T11:05:00+00:00"},
            {"title": "Выход из зоны", "details": "Alina · Office",
             "timestamp": "2026-10-18T11:06:00+00:00"},
        ]
        for path, embedded in cards:
            standalone = yaml.safe_load(path.read_text(encoding="utf-8"))
            with self.subTest(card=path.name):
                self.assertEqual(standalone, embedded)
                for card in (standalone, embedded):
                    template = env.from_string(card["content"])

                    def render(roster_arg, events_arg):
                        return template.render(
                            state_attr=lambda _, attr: (
                                roster_arg if attr == "residents" else events_arg),
                            as_datetime=datetime.fromisoformat,
                            as_local=lambda value: value,
                        ).strip()

                    rendered = render(roster, event_rows)
                    self.assertNotIn("device_tracker.legacy", rendered)
                    self.assertNotIn("──────────────────", rendered)
                    self.assertNotIn("<table", rendered)
                    one = render({"one": roster["one"]}, event_rows[:1])
                    empty = render({}, [])
                    if path == REGISTERED:
                        pre = '<pre style="margin:0; padding:0; line-height:1; ' \
                              'font-family:\'Courier New\',monospace; white-space:pre;">'
                        self.assertTrue(rendered.startswith(pre + "Зарегистрированные телефоны\n"))
                        self.assertTrue(rendered.endswith("</pre>"))
                        self.assertEqual(rendered.count("<pre"), 1)
                        self.assertEqual(rendered.count("</pre>"), 1)
                        self.assertNotIn("```", rendered)
                        self.assertIn("├─ 📱 Serzhan (iPhone)", rendered)
                        self.assertIn("│  ├─ GPS · phone_1", rendered)
                        self.assertIn("│  └─ Wi-Fi · router_1", rendered)
                        self.assertIn("└─ 📱 Alina (iPhone)", rendered)
                        self.assertNotIn("device_tracker.phone_1", rendered)
                        self.assertNotIn("device_tracker.router_1", rendered)
                        self.assertNotIn("device_tracker.phone_2", rendered)
                        self.assertNotIn("title", card)
                        # PVE native <pre> has no Markdown code-block padding
                        # or extra blank lines; every node remains one line.
                        self.assertEqual(len(rendered.splitlines()), 7)
                        self.assertTrue(all(line.strip() for line in rendered.splitlines()))
                        self.assertNotIn("\n\n", rendered)
                        self.assertEqual(rendered.count("line-height:1"), 1)
                        # Registered labels originate from HA users/devices:
                        # never inject unescaped HTML into the raw <pre>.
                        unsafe = dict(roster["one"],
                                      registration_label='Phone <script>x</script> & X')
                        html = render({"one": unsafe}, [])
                        self.assertNotIn("<script>", html)
                        self.assertIn("&lt;script&gt;", html)
                        self.assertIn("&amp;", html)
                        self.assertIn("   └─ Wi-Fi · не привязан", rendered)
                        self.assertIn("└─ 📱 Serzhan (iPhone)", one)
                        self.assertNotIn("├─ 📱", one)
                        self.assertEqual(empty, "_Нет зарегистрированных телефонов._")
                        self.assertEqual(render(None, []),
                                         "_Реестр телефонов пока недоступен._")
                    else:
                        self.assertTrue(rendered.startswith(
                            "| № | Дата и время | Событие | Детали |\n"
                            "|:--:|:--|:--|:--|\n"))
                        self.assertEqual(len(rendered.splitlines()), 4)
                        self.assertIn("| 1 | 18.10.2026 11:05 | GPS: дома | Serzhan (iPhone) |",
                                      rendered)
                        self.assertIn("| 2 | 18.10.2026 11:06 | Выход из зоны | Alina · Office |",
                                      rendered)
                        self.assertEqual(len(one.splitlines()), 3)
                        self.assertEqual(empty, "_Событий пока нет._")

    def test_dashboard_four_independent_sections_and_dynamic_source_filters(self):
        dashboard = yaml.safe_load(DASH.read_text(encoding="utf-8"))
        self.assertEqual(dashboard["type"], "sections")
        self.assertEqual(dashboard["max_columns"], 4)
        self.assertEqual(dashboard["cards"], [])
        sections = dashboard["sections"]
        self.assertEqual(len(sections), 4)
        for section in sections:
            self.assertEqual(section["type"], "grid")
        presence, residents, notifications, debug = [s["cards"] for s in sections]
        self.assertEqual(presence[0]["heading"], "Присутствие")
        self.assertEqual(presence[1]["type"], "vertical-stack")
        self.assertEqual(presence[1]["cards"][0]["type"], "custom:button-card")
        self.assertEqual(presence[1]["cards"][1]["type"], "custom:mushroom-chips-card")
        self.assertEqual(presence[2]["name"], "Регистрация телефона")
        self.assertEqual(residents[0]["heading"], "Жильцы")
        self.assertEqual(len(residents), 7)
        self.assertEqual(residents[1], yaml.safe_load(REGISTERED.read_text(encoding="utf-8")))
        # Like the DH PVE Agent VM/LXC tree, the monospace layout needs a
        # full 12-column span to avoid wrapped tracker IDs looking double-spaced.
        self.assertEqual(residents[1]["grid_options"], {"columns": 12})
        self.assertEqual(yaml.safe_load(REGISTERED.read_text(encoding="utf-8"))["grid_options"],
                         {"columns": 12})
        self.assertEqual(residents[2]["name"], "Управление телефонами · администратор")
        self.assertIn("hass.user?.is_admin !== true", residents[2]["hidden"])
        self.assertEqual(residents[3]["card_param"], "cards")
        self.assertEqual(residents[3]["filter"]["include"][0]["entity_id"],
                         "binary_sensor.dh_presence_app_*_wifi_home")
        for card, source_file in ((residents[4], GPS_SOURCES),
                                  (residents[5], WIFI_SOURCES),
                                  (residents[6], ZONE_COUNTS)):
            source_card = yaml.safe_load(source_file.read_text(encoding="utf-8"))
            self.assertEqual(card, source_card)
        self.assertEqual(notifications[0]["heading"], "Уведомления")
        self.assertEqual(notifications[1]["type"], "custom:auto-entities")
        self.assertEqual(notifications[1]["filter"]["include"][0]["entity_id"],
                         "switch.dh_presence_app_notify_zone_*")
        self.assertEqual([e["entity"] for e in notifications[2]["entities"]], [
            "switch.dh_presence_app_notify_gps",
            "switch.dh_presence_app_notify_wifi"])
        self.assertEqual(debug[0]["heading"].strip(), "Временная карточка (debug)")
        self.assertEqual(debug[1]["cards"][0]["type"], "custom:auto-entities")
        self.assertEqual(debug[1]["cards"][0]["sort"]["method"], "entity_id")
        self.assertEqual(debug[1]["grid_options"]["columns"], 12)

    def test_dynamic_zone_people_card_uses_native_zone_domain(self):
        # HA zone entity state is its number of person entities inside
        # the zone. We intentionally do not duplicate or recompute counts.
        text = ZONE_COUNTS.read_text(encoding="utf-8")
        card = yaml.safe_load(text)
        self.assertEqual(card["type"], "custom:auto-entities")
        self.assertEqual(card["card"]["type"], "entities")
        self.assertIn("количество людей", card["card"]["title"])
        self.assertEqual(card["filter"], {"include": [{"domain": "zone"}]})
        self.assertEqual(card["sort"]["method"], "name")
        self.assertTrue(card["unique"])
        self.assertFalse(card["show_empty"])
        self.assertNotIn("zone.home", text)
        self.assertNotIn("person.", text)
        self.assertNotIn("device_tracker.", text)
        self.assertNotIn("state:", text)

    def test_yaml_and_styles_icon_js_block(self):
        for path in (CARD, DASH):
            with self.subTest(path=path.name):
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
                if path == CARD:
                    status = document["cards"][0]
                else:
                    status = document["sections"][0]["cards"][1]["cards"][0]
                self.assertEqual(status["type"], "custom:button-card")
                styles = status["styles"]
                icon = styles["icon"]
                self.assertIsInstance(icon, list)
                self.assertEqual(icon[0], {"width": "28px"})
                color = icon[1]["color"]
                self.assertIsInstance(color, str)
                self.assertTrue(color.strip().startswith("[[["), color[:100])
                self.assertTrue(color.strip().endswith("]]]"), color[-100:])
                self.assertIn("update.digitalhouses_presence_app_update", color)
                for key in ("icon", "name", "label"):
                    js = status[key]
                    self.assertIsInstance(js, str)
                    self.assertTrue(js.strip().startswith("[[["))
                    self.assertTrue(js.strip().endswith("]]]"))


if __name__ == "__main__":
    unittest.main()
