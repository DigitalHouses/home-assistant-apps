"""Registered-phone dashboard tree: App-only formatting and recorder isolation."""
import json
import unittest
from unittest.mock import Mock

from app import publish_snapshot
from dh_presence.core import Engine, Status
from dh_presence.discovery import discovery, topic
from dh_presence.phone_tree import registered_phones_tree


def enrolled(tracker, name, *, ip="192.168.8.54", mac="88:b9:45:80:a7:55",
             user="Serzhan", wifi=None):
    return {"tracker": tracker, "user_name": user, "device_name": name,
            "ip": ip, "mac": mac, "wifi_tracker": wifi}


class TestDashboardRegistrationTree(unittest.TestCase):
    def test_app_prepares_exact_tree_for_dashboard_and_filters_untracked(self):
        engine = Engine()
        engine.add("device_tracker.s_iphone", "13ProMAX .SKY", registered=True)
        engine.add("device_tracker.alina", "iPhone", registered=True)
        engine.add("device_tracker.admin", "Excluded", registered=False)
        # Each branch represents its source, not the overall presence mode.
        engine.residents["device_tracker.s_iphone"].gps = Status.HOME
        engine.residents["device_tracker.s_iphone"].wifi = Status.NOT_HOME
        engine.residents["device_tracker.alina"].gps = Status.NOT_HOME
        regs = [
            enrolled("device_tracker.s_iphone", "13ProMAX .SKY",
                     wifi="device_tracker.s_router"),
            enrolled("device_tracker.admin", "Private admin", user="Administrator"),
            enrolled("device_tracker.alina", "iPhone", user="Alina",
                     wifi=None, ip="192.168.8.55", mac="8a:43:3e:74:09:83"),
        ]
        doc = registered_phones_tree(regs, list(engine.residents.values()))
        self.assertEqual(doc["count"], 2)
        self.assertEqual(doc["tree"].split("\n"), [
            "Зарегистрированные телефоны",
            "├─ 📲 Alina (iPhone)",
            "│  ├─ GPS · 🟠 Не дома · alina",
            "│  ├─ Wi-Fi · ⚪ Не привязан",
            "│  ├─ IP (рег.) · 192.168.8.55",
            "│  └─ MAC (рег.) · 8a:43:3e:74:09:83",
            "└─ 📲 Serzhan (13ProMAX .SKY)",
            "   ├─ GPS · 🟢 Дома · s_iphone",
            "   ├─ Wi-Fi · 🟠 Не дома · s_router",
            "   ├─ IP (рег.) · 192.168.8.54",
            "   └─ MAC (рег.) · 88:b9:45:80:a7:55",
        ])
        self.assertNotIn("Administrator", doc["tree"])
        self.assertNotIn("\n\n", doc["tree"])
        self.assertEqual(registered_phones_tree([], list(engine.residents.values())),
                         {"count": 0, "tree": "Зарегистрированные телефоны"})
        # Registration was deleted; no stale retained details may survive.
        engine.residents.pop("device_tracker.alina")
        gone = registered_phones_tree(regs, list(engine.residents.values()))
        self.assertNotIn("8a:43:3e:74:09:83", gone["tree"])
        self.assertNotIn("192.168.8.55", gone["tree"])

    def test_source_transitions_update_tree_without_registry_changes(self):
        engine = Engine()
        engine.add("device_tracker.phone", "iPhone", registered=True)
        resident = engine.residents["device_tracker.phone"]
        record = enrolled("device_tracker.phone", "iPhone",
                          wifi="device_tracker.router")
        original = registered_phones_tree([record], [resident])
        self.assertIn("GPS · ⚪ Недоступно · phone", original["tree"])
        self.assertIn("Wi-Fi · ⚪ Недоступно · router", original["tree"])
        self.assertNotIn("🟠 Не дома", original["tree"])

        resident.gps = Status.HOME
        resident.wifi = Status.HOME
        home = registered_phones_tree([record], [resident])
        self.assertEqual(home["count"], original["count"])
        self.assertIn("GPS · 🟢 Дома · phone", home["tree"])
        self.assertIn("Wi-Fi · 🟢 Дома · router", home["tree"])
        self.assertNotEqual(home["tree"], original["tree"])

        resident.gps = Status.NOT_HOME
        resident.wifi = Status.NOT_HOME
        away = registered_phones_tree([record], [resident])
        self.assertIn("GPS · 🟠 Не дома · phone", away["tree"])
        self.assertIn("Wi-Fi · 🟠 Не дома · router", away["tree"])
        self.assertNotEqual(away["tree"], home["tree"])

        # Router/API outage is not evidence of Wi-Fi absence.
        resident.wifi = Status.UNAVAILABLE
        unavailable = registered_phones_tree([record], [resident])
        self.assertIn("Wi-Fi · ⚪ Недоступно · router", unavailable["tree"])
        self.assertNotIn("Wi-Fi · 🟠 Не дома", unavailable["tree"])
        self.assertEqual(unavailable,
                         registered_phones_tree([record], [resident]))

    def test_wifi_without_router_link_is_not_false_away(self):
        engine = Engine()
        engine.add("device_tracker.phone", "iPhone", registered=True)
        resident = engine.residents["device_tracker.phone"]
        resident.gps = Status.HOME
        resident.wifi = Status.NOT_HOME
        row = enrolled("device_tracker.phone", "iPhone", wifi=None)
        doc = registered_phones_tree([row], [resident])
        self.assertIn("GPS · 🟢 Дома · phone", doc["tree"])
        self.assertIn("Wi-Fi · ⚪ Не привязан", doc["tree"])
        self.assertNotIn("Wi-Fi · 🟠 Не дома", doc["tree"])

    def test_untrusted_registration_names_cannot_create_spoofed_branches(self):
        engine = Engine()
        engine.add("device_tracker.p", "Phone", registered=True)
        reg = enrolled("device_tracker.p", "Device\n└─ fake", user="<script>x</script>\rAdmin")
        doc = registered_phones_tree([reg], list(engine.residents.values()))
        self.assertEqual(len(doc["tree"].splitlines()), 6)
        self.assertIn("Device └─ fake", doc["tree"])
        self.assertNotIn("\n└─ fake", doc["tree"])

    def test_separate_discovery_topic_and_clean_existing_aggregate(self):
        engine = Engine()
        engine.add("device_tracker.p", "Phone", registered=True)
        reg = enrolled("device_tracker.p", "Phone")
        comps = discovery("0.1.31", list(engine.residents.values()))["components"]
        sensor = comps["registered_phones"]
        self.assertEqual(sensor["default_entity_id"], "sensor.dh_presence_app_registered_phones")
        self.assertEqual(sensor["state_topic"], topic("registrations/tree"))
        self.assertEqual(sensor["json_attributes_topic"], topic("registrations/tree"))
        self.assertEqual(sensor["entity_category"], "diagnostic")
        self.assertNotIn("registrations/tree", json.dumps(comps["residents_home"]))
        self.assertNotIn("ip", json.dumps(comps["residents_home"]).lower())
        self.assertNotIn("mac", json.dumps(comps["residents_home"]).lower())
        self.assertNotIn(reg["ip"], json.dumps(engine.snapshot()))
        self.assertNotIn(reg["mac"], json.dumps(engine.snapshot()))

    def test_runtime_publishes_private_tree_separately_from_state(self):
        engine = Engine()
        engine.add("device_tracker.p", "Phone", registered=True)
        reg = enrolled("device_tracker.p", "Phone")
        mqtt = Mock()
        mqtt.publish.return_value = True
        operations = Mock()
        operations.snapshot.return_value = {"card": {"state": "running"}}
        ok = publish_snapshot(mqtt, engine, "0.1.31", "2026-10-19T12:00:00+00:00",
                              operations, None, registrations=[reg])
        self.assertTrue(ok)
        publishes = [(x.args[0], x.args[1]) for x in mqtt.publish.call_args_list]
        by_topic = dict(publishes)
        self.assertEqual(by_topic[topic("registrations/tree")]["count"], 1)
        self.assertIn(reg["ip"], by_topic[topic("registrations/tree")]["tree"])
        self.assertNotIn(reg["ip"], json.dumps(by_topic[topic("state")]))
        self.assertNotIn(reg["mac"], json.dumps(by_topic[topic("state")]))
        # A failed registry publish must fail the snapshot instead of
        # reporting a successful refresh with stale IP/MAC data.
        def publish(topic_name, _value):
            return topic_name != topic("registrations/tree")
        mqtt.publish.side_effect = publish
        self.assertFalse(publish_snapshot(
            mqtt, engine, "0.1.31", "2026-10-19T12:00:00+00:00",
            operations, None, registrations=[reg]))


if __name__ == "__main__":
    unittest.main()
