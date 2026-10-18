"""Zone events use HA classification, persistent baselines and safe MQTT controls."""
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

from dh_presence.zones import ZoneMonitor, zone_catalog, zone_key, classify
from dh_presence.discovery import discovery, with_cleanup, topic
from dh_presence.notifications import NotificationSelection


T = datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)
ZONES = {"zone.home": "Дом", "zone.office": "Office", "zone.school": "School"}


class ZoneTests(unittest.TestCase):
    def test_catalog_is_ha_zone_only_and_never_uses_population(self):
        states = [
            {"entity_id": "zone.home", "state": "3", "attributes": {"friendly_name": "Дом"}},
            {"entity_id": "zone.office", "state": "1", "attributes": {"friendly_name": "Office"}},
            {"entity_id": "person.someone", "state": "Office", "attributes": {}},
        ]
        self.assertEqual(zone_catalog(states), {"zone.home": "Дом", "zone.office": "Office"})
        self.assertEqual(classify("home", ZONES), "zone.home")
        self.assertEqual(classify("Office", ZONES), "zone.office")
        self.assertEqual(classify("not_home", ZONES), "")
        self.assertIsNone(classify("unavailable", ZONES))
        self.assertIsNone(classify("Office", {"zone.one": "Office", "zone.two": "Office"}))

    def test_no_startup_or_repeated_events_and_restart_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "zone.json")
            monitor = ZoneMonitor(path)
            self.assertEqual(monitor.observe("r", "home", T, ZONES), [])
            self.assertEqual(monitor.observe("r", "home", T, ZONES), [])
            self.assertEqual(monitor.observe("r", "home", T + timedelta(minutes=1), ZONES), [])
            monitor = ZoneMonitor(path)
            self.assertEqual(monitor.observe("r", "home", T + timedelta(minutes=2), ZONES), [])
            changed = monitor.observe("r", "Office", T + timedelta(minutes=3), ZONES)
            self.assertEqual([v["event_type"] for v in changed], ["zone_leave", "zone_enter"])
            self.assertEqual([v["zone_entity_id"] for v in changed], ["zone.home", "zone.office"])
            self.assertEqual(changed[1]["zone_key"], zone_key("zone.office"))
            self.assertEqual(monitor.observe("r", "Office", T + timedelta(minutes=3), ZONES), [])

    def test_unavailable_stale_and_removed_zone_are_not_departures(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor = ZoneMonitor(str(Path(tmp) / "zones.json"))
            monitor.observe("r", "Office", T, ZONES)
            self.assertEqual(monitor.observe("r", "unavailable", T + timedelta(minutes=2), ZONES), [])
            self.assertEqual(monitor.observe("r", "not_home", T - timedelta(minutes=1), ZONES), [])
            changed = monitor.observe("r", "School", T + timedelta(minutes=3), ZONES)
            self.assertEqual([e["event_type"] for e in changed], ["zone_leave", "zone_enter"])
            removed = {"zone.home": "Дом", "zone.school": "School"}
            self.assertEqual(monitor.observe("r", "not_home", T + timedelta(minutes=4), removed),
                             [dict(event_type="zone_leave", resident_id="r", source="gps",
                                   observed_at=(T + timedelta(minutes=4)).isoformat(),
                                   zone_entity_id="zone.school", zone_name="School",
                                   zone_key=zone_key("zone.school"))])

    def test_switches_default_off_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            import json
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"schema_version": 1, "enabled": {
                "presence": True, "gps": True, "wifi": False}}))
            settings = NotificationSelection(str(path))
            self.assertEqual(settings.enabled, {"gps": True, "wifi": False})
            self.assertTrue(settings.sync_zones(ZONES))
            self.assertFalse(settings.sync_zones(ZONES))
            self.assertEqual(settings.mqtt_state("zones/" + zone_key("zone.office")), "OFF")
            settings.change("zones/" + zone_key("zone.office"), "ON")
            restored = NotificationSelection(str(path))
            self.assertEqual(restored.mqtt_state("zones/" + zone_key("zone.office")), "ON")
            with self.assertRaises(ValueError):
                restored.change("zones/ffffffffffffffff", "ON")

    def test_discovery_cleanup_old_switch_and_removed_zones(self):
        before = discovery("0.1.26", [], ZONES)
        after = discovery("0.1.27", [], {"zone.home": "Дом"})
        self.assertEqual(before["device"]["identifiers"], after["device"]["identifiers"])
        diff = with_cleanup(before, after)["components"]
        self.assertEqual(diff["notify_zone_" + zone_key("zone.office")], {"platform": "switch"})
        self.assertEqual(diff["notify_zone_" + zone_key("zone.school")], {"platform": "switch"})
        self.assertNotIn("notify_presence", after["components"])
        self.assertIn("zone_enter", after["components"]["event"]["event_types"])
        self.assertEqual(
            after["components"]["notify_zone_" + zone_key("zone.home")]["command_topic"],
            topic("notifications/zones/" + zone_key("zone.home") + "/set"))


if __name__ == "__main__":
    unittest.main()
