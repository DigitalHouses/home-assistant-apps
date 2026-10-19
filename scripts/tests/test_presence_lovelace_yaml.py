"""Parse the maintained Presence Lovelace YAML and validate its button-card structure.

Lives in repository-contract tests because PyYAML is installed in that CI job.
The Presence runtime unit test job intentionally does not depend on PyYAML.
"""
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
import hashlib

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
ADMIN_SELECT = ROOT / "examples/lovelace/presence_admin_remove_phone_card_ru.yaml"
NOTIFICATIONS_PACKAGE = ROOT / "examples/packages/dh_presence_app_notification_merge_named_ru.yaml"
RESIDENTS = ROOT / "examples/lovelace/presence_residents_auto_entities_ru.yaml"


class PresenceLovelaceYamlTests(unittest.TestCase):
    def test_notification_policy_emits_one_user_message_and_optional_wifi(self):
        """Exercise the actual shipped HA package templates and switch policy.

        This simulates HA's trigger.id / condition:state / Jinja template
        evaluation, not a fabricated copy of the notification strings.
        """
        package = yaml.safe_load(NOTIFICATIONS_PACKAGE.read_text(encoding="utf-8"))
        auto = package["dh_presence_app_notification"]["automation"][0]
        self.assertEqual(auto["id"], "dh_presence_notifications")
        self.assertEqual(auto["alias"], "DH Presence Notifications")
        branches = auto["actions"][0]["choose"]
        self.assertEqual(len(branches), 7)
        self.assertEqual(len(auto["triggers"]), 7)
        self.assertEqual(package["dh_presence_app_notification"]["homeassistant"]["customize"][
            "automation.dh_presence_notifications"]["friendly_name"],
            "DH Presence · Уведомления")
        env = Environment()
        home_key = hashlib.sha256(b"zone.home").hexdigest()[:16]
        urban_key = hashlib.sha256(b"zone.urban_coffee").hexdigest()[:16]
        self.assertEqual(home_key, "620b51c29b479984")

        def fire(event_type, attrs=None, enabled=()):
            payload = {"user_name": "Serzhan", "device_name": "13ProMAX .SKY"}
            payload.update(attrs or {})
            trigger = {"to_state": {"attributes": payload}}
            on = set(enabled)

            def is_state(entity, state):
                return entity in on and state == "on"

            vars_ = {
                key: env.from_string(value).render(trigger=trigger).strip()
                for key, value in auto["variables"].items()
            }
            delivered = []
            for branch in branches:
                satisfied = True
                for cond in branch["conditions"]:
                    if cond["condition"] == "trigger":
                        satisfied = event_type == cond["id"]
                    elif cond["condition"] == "state":
                        satisfied = is_state(cond["entity_id"], cond["state"])
                    elif cond["condition"] == "template":
                        rendered = env.from_string(cond["value_template"]).render(
                            trigger=trigger, is_state=is_state).strip()
                        satisfied = rendered == "True"
                    else:
                        raise AssertionError("Unexpected condition " + str(cond))
                    if not satisfied:
                        break
                if satisfied:
                    action = branch["sequence"][0]
                    self.assertEqual(action["action"], "script.write2log")
                    rendered = {
                        key: env.from_string(value).render(
                            trigger=trigger, **vars_).strip()
                        for key, value in action["data"].items()
                    }
                    delivered.append(rendered)
                    break  # Native HA choose executes the first matching branch.
            return delivered

        home = "switch.dh_presence_app_notify_zone_" + home_key
        urban = "switch.dh_presence_app_notify_zone_" + urban_key
        wifi = "switch.dh_presence_app_notify_wifi"
        cases = [
            ("arrival", {"first_arrival": True, "residents_home_after": 1}, (home,),
             "🏠✅ Serzhan прибыл домой", "Статус дома: ПРИСУТСТВИЕ"),
            ("arrival", {"first_arrival": False, "residents_home_after": 2}, (home,),
             "🏠✅ Serzhan прибыл домой", "Дома 2 человека"),
            ("departure", {"last_departure": False, "residents_home_after": 1}, (home,),
             "🏠🚪 Serzhan покинул дом", "Дома 1 человек"),
            ("departure", {"last_departure": True, "residents_home_after": 0}, (home,),
             "🏠🚪 Serzhan покинул дом", "Статус дома: ОТСУТСТВИЕ"),
            ("zone_enter", {"zone_entity_id": "zone.urban_coffee",
                            "zone_name": "Urban coffee", "zone_key": urban_key}, (urban,),
             "📍✅ Serzhan прибыл в Urban coffee", "Местоположение подтверждено GPS."),
            ("zone_leave", {"zone_entity_id": "zone.urban_coffee",
                            "zone_name": "Urban coffee", "zone_key": urban_key}, (urban,),
             "📍🚪 Serzhan покинул Urban coffee", "Местоположение подтверждено GPS."),
            ("wifi_in", {}, (wifi,),
             "📶✅ Подключение к Wi-Fi сети",
             "Устройство Serzhan (13ProMAX .SKY) подключено к домашней Wi-Fi сети."),
            ("wifi_out", {}, (wifi,),
             "📶❌ Отключение от Wi-Fi сети",
             "Устройство Serzhan (13ProMAX .SKY) отключилось от домашней Wi-Fi сети."),
        ]
        for event_type, attrs, enabled, title, message in cases:
            with self.subTest(event_type=event_type, attrs=attrs):
                self.assertEqual(fire(event_type, attrs, enabled),
                                 [{"title": title, "message": message}])

        # Russian agreement for zero, singular, paucal (2-4), 5+, and
        # the 11-14 exception, including all hundreds variants.
        grammatical_cases = {
            0: "человек",
            1: "человек",
            2: "человека",
            3: "человека",
            4: "человека",
            5: "человек",
            11: "человек",
            12: "человек",
            13: "человек",
            14: "человек",
            15: "человек",
            20: "человек",
            21: "человек",
            22: "человека",
            23: "человека",
            24: "человека",
            25: "человек",
            101: "человек",
            102: "человека",
            104: "человека",
            111: "человек",
            112: "человек",
            114: "человек",
            121: "человек",
            122: "человека",
            125: "человек",
        }
        for count, word in grammatical_cases.items():
            for kind, first_or_last in (("arrival", "first_arrival"),
                                        ("departure", "last_departure")):
                with self.subTest(event_type=kind, count=count):
                    actual = fire(kind, {first_or_last: False,
                                         "residents_home_after": count}, (home,))
                    self.assertEqual(actual[0]["message"],
                                     f"Дома {count} {word}")
        for missing_count in (None, "?", ""):
            self.assertEqual(
                fire("arrival", {"first_arrival": False,
                                 "residents_home_after": missing_count}, (home,))[0]["message"],
                "Дома: нет данных"
            )
        # Do not replace explicit first/last household statuses with counts.
        self.assertEqual(fire("arrival", {"first_arrival": True,
                                          "residents_home_after": 1}, (home,))[0]["message"],
                         "Статус дома: ПРИСУТСТВИЕ")
        self.assertEqual(fire("departure", {"last_departure": True,
                                            "residents_home_after": 0}, (home,))[0]["message"],
                         "Статус дома: ОТСУТСТВИЕ")

        # No second zone.home notification when an arrival/departure is
        # already covered by the logical home state.
        home_event = {"zone_entity_id": "zone.home", "zone_name": "Дом", "zone_key": home_key}
        for event_type in ("zone_enter", "zone_leave"):
            self.assertEqual(fire(event_type, home_event, (home,)), [])

        self.assertEqual(fire("arrival", {"first_arrival": True}, ()), [])
        self.assertEqual(fire("zone_enter", cases[4][1], ()), [])
        self.assertEqual(fire("wifi_in", {}, ()), [])
        self.assertEqual(fire("wifi_lost", {}, (wifi,)), [])
        for event_type in ("gps_in", "gps_out"):
            self.assertEqual(fire(event_type, {}, (home, wifi, urban)), [])
        # Wi-Fi remains separately opt-in even when no zone switch is enabled.
        self.assertEqual(len(fire("wifi_in", {}, (wifi,))), 1)
        # Notifications are about the device, not the resident's grammatical gender.
        female = {"user_name": "Anel", "device_name": "Anelkin15"}
        self.assertEqual(
            fire("wifi_in", female, (wifi,)),
            [{"title": "📶✅ Подключение к Wi-Fi сети",
              "message": "Устройство Anel (Anelkin15) подключено к домашней Wi-Fi сети."}])
        self.assertEqual(
            fire("wifi_out", female, (wifi,)),
            [{"title": "📶❌ Отключение от Wi-Fi сети",
              "message": "Устройство Anel (Anelkin15) отключилось от домашней Wi-Fi сети."}])

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
        """The App prepares the full phone tree, HA only displays its text."""
        dashboard = yaml.safe_load(DASH.read_text(encoding="utf-8"))
        residents = dashboard["sections"][1]["cards"]
        notifications = dashboard["sections"][2]["cards"]
        cards = ((REGISTERED, residents[1]), (RECENT, notifications[3]))
        env = Environment()
        events = [
            {"title": "GPS: дома", "details": "Serzhan (iPhone)",
             "timestamp": "2026-10-18T11:05:00+00:00"},
            {"title": "Выход из зоны", "details": "Alina · Office",
             "timestamp": "2026-10-18T11:06:00+00:00"},
        ]
        tree = ("Зарегистрированные телефоны\n"
                "└─ 📱 Serzhan (13ProMAX .SKY)\n"
                "   ├─ GPS · 13promax_sky\n"
                "   ├─ Wi-Fi · не привязан\n"
                "   ├─ IP (рег.) · 192.168.8.54\n"
                "   └─ MAC (рег.) · 88:b9:45:80:a7:55")
        for path, embedded in cards:
            standalone = yaml.safe_load(path.read_text(encoding="utf-8"))
            with self.subTest(card=path.name):
                self.assertEqual(standalone, embedded)
                for card in (standalone, embedded):
                    template = env.from_string(card["content"])

                    def render(tree_value, event_rows):
                        return template.render(
                            state_attr=lambda _, attr: tree_value if attr == "tree" else event_rows,
                            as_datetime=datetime.fromisoformat,
                            as_local=lambda value: value,
                        ).strip()

                    output = render(tree, events)
                    self.assertNotIn("──────────────────", output)
                    if path == REGISTERED:
                        opening = ("<pre style=\"margin:0; padding:0; line-height:1; "
                                   "font-family:'Courier New',monospace; white-space:pre;\">")
                        self.assertEqual(output, opening + tree + "</pre>")
                        self.assertIn("IP (рег.) · 192.168.8.54", output)
                        self.assertIn("MAC (рег.) · 88:b9:45:80:a7:55", output)
                        self.assertNotIn("residents_home", card["content"])
                        self.assertNotIn("phone.", card["content"])
                        self.assertIn("sensor.dh_presence_app_registered_phones", card["content"])
                        self.assertEqual(render(None, events),
                                         "_Реестр телефонов пока недоступен._")
                        self.assertIn("&lt;script&gt;", render("<script>", events))
                        self.assertEqual(card["grid_options"], {"columns": 12})
                    else:
                        self.assertTrue(output.startswith(
                            "| № | Дата и время | Событие | Детали |\n"
                            "|:--:|:--|:--|:--|\n"))
                        self.assertEqual(len(output.splitlines()), 4)
                        self.assertIn("GPS: дома", output)
                        self.assertEqual(render(tree, []), "_Событий пока нет._")

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
        administrator = residents[2]
        self.assertEqual(administrator, yaml.safe_load(ADMIN_SELECT.read_text(encoding="utf-8")))
        self.assertEqual(administrator["type"], "custom:button-card")
        self.assertIn("hass.user?.is_admin !== true", administrator["hidden"])
        wrapper = administrator["custom_fields"]["manager"]["card"]
        self.assertEqual(wrapper["type"], "entities")
        self.assertEqual([e["entity"] for e in wrapper["entities"]], [
            "select.dh_presence_app_remove_phone",
            "button.dh_presence_app_delete_registration"])
        action = wrapper["entities"][1]["tap_action"]
        self.assertEqual(action["action"], "perform-action")
        self.assertEqual(action["perform_action"], "button.press")
        self.assertEqual(action["target"]["entity_id"],
                         "button.dh_presence_app_delete_registration")
        self.assertIn("confirmation", action)
        self.assertNotIn("addon-iframe", str(administrator))
        self.assertEqual(administrator["grid_options"], {"columns": 12})
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

    def test_resident_mushroom_card_relative_status_age(self):
        """The shipped standalone and dashboard template must agree exactly.

        Use a pinned HA-local test clock to verify grammatical Russian relative
        durations, missing timestamps, and router source wording. The template
        contains now(), which triggers HA to re-render once per minute.
        """
        standalone = yaml.safe_load(RESIDENTS.read_text(encoding="utf-8"))
        dashboard = yaml.safe_load(DASH.read_text(encoding="utf-8"))
        embedded = dashboard["sections"][1]["cards"][3]
        self.assertEqual(embedded, standalone)
        self.assertEqual(standalone["type"], "custom:auto-entities")
        self.assertEqual(standalone["filter"]["include"][0]["entity_id"],
                         "binary_sensor.dh_presence_app_*_wifi_home")
        card = standalone["filter"]["include"][0]["options"]
        self.assertEqual(card["type"], "custom:mushroom-template-card")
        self.assertTrue(card["multiline_secondary"])
        self.assertEqual(card["tap_action"], {"action": "more-info"})
        self.assertNotIn("tojson", card["secondary"])
        self.assertNotIn("ARP", card["secondary"])
        self.assertIn("now()", card["secondary"])
        self.assertIn("status_changed_at", card["secondary"])
        self.assertIn("gps_changed_at", card["secondary"])
        self.assertIn("wifi_changed_at", card["secondary"])
        self.assertNotIn("strftime", card["secondary"])

        template = Environment().from_string(card["secondary"])
        instant = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

        def as_timestamp(value, default=None):
            if value is None:
                return default
            if isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value)
                except ValueError:
                    return default
            return value.timestamp()

        def render(total_minutes, *, gps_minutes=None, wifi_minutes=None,
                   missing=False):
            def stamp(minutes):
                return ((instant - timedelta(minutes=minutes)).isoformat()
                        if minutes is not None else None)
            resident = {
                "name": "13ProMAX .SKY",
                "user_name": "Serzhan",
                "status": "home",
                "gps": "home",
                "wifi": "not_home",
                "status_changed_at": None if missing else stamp(total_minutes),
                "gps_changed_at": stamp(gps_minutes),
                "wifi_changed_at": stamp(wifi_minutes),
            }
            roster = {"abc": resident}
            result = template.render(
                entity="binary_sensor.dh_presence_app_abc_wifi_home",
                state_attr=lambda entity_id, attribute: roster,
                as_timestamp=as_timestamp,
                now=lambda: instant,
            ).strip()
            return result

        self.assertEqual(render(120, gps_minutes=60, wifi_minutes=5),
                         "Итог: Дома · 2 часа назад\n"
                         "GPS: Дома · 1 час назад\n"
                         "Wi-Fi: Не подключён (роутер) · 5 минут назад")
        self.assertEqual(render(60, missing=True), "Итог: Дома · —\n"
                         "GPS: Дома · —\nWi-Fi: Не подключён (роутер) · —")

        examples = {
            0: "только что",
            1: "1 минуту назад",
            2: "2 минуты назад",
            5: "5 минут назад",
            11: "11 минут назад",
            21: "21 минуту назад",
            22: "22 минуты назад",
            60: "1 час назад",
            120: "2 часа назад",
            300: "5 часов назад",
            660: "11 часов назад",
            1260: "21 час назад",
            1440: "1 день назад",
            2880: "2 дня назад",
            7200: "5 дней назад",
            15840: "11 дней назад",
            30240: "21 день назад",
        }
        for minutes, phrase in examples.items():
            with self.subTest(minutes=minutes):
                self.assertIn("Итог: Дома · " + phrase,
                              render(minutes).splitlines())

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
