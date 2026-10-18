"""Executable regression contract for the multi-network Zigbee2MQTT MQTT core."""

import json
import unittest

from zigbee_monitor import ZigbeeMonitor, ZigbeeMonitorError, parse_networks


IEEE1 = "0x00158d0000000001"
IEEE2 = "0x00158d0000000002"
IEEE3 = "0x00158d0000000003"


def network_configs():
    return parse_networks([
        {"network_id": "floor_1", "base_topic": "z2m_1", "name": "Первый этаж"},
        {"network_id": "floor_2", "base_topic": "z2m_2", "name": "Второй этаж"},
    ])


def inventory(*items):
    return json.dumps(items, ensure_ascii=False).encode("utf-8")


def device(ieee=IEEE1, name="bedroom", kind="Router", model="TRV-1"):
    return {
        "ieee_address": ieee,
        "friendly_name": name,
        "type": kind,
        "definition": {"model": model, "vendor": "Vendor"},
    }


class NetworkConfigTests(unittest.TestCase):
    def test_valid_immutable_ids_and_topic(self):
        networks = network_configs()
        self.assertEqual([n.network_id for n in networks], ["floor_1", "floor_2"])
        self.assertEqual(networks[1].base_topic, "z2m_2")

    def test_reject_duplicate_and_nested_topics(self):
        with self.assertRaisesRegex(ZigbeeMonitorError, "duplicate base_topic"):
            parse_networks([
                {"network_id": "a", "base_topic": "zigbee2mqtt", "name": "One"},
                {"network_id": "b", "base_topic": "zigbee2mqtt", "name": "Two"},
            ])
        with self.assertRaisesRegex(ZigbeeMonitorError, "nested"):
            parse_networks([
                {"network_id": "a", "base_topic": "zigbee2mqtt", "name": "One"},
                {"network_id": "b", "base_topic": "zigbee2mqtt/floor", "name": "Two"},
            ])

    def test_reject_invalid_config(self):
        for bad in ([], {}, None, "z2m"):
            with self.subTest(raw=bad), self.assertRaises(ZigbeeMonitorError):
                parse_networks(bad)
        for topic in ("z2m/#", "/z2m", "z2m/", "z2m/+/x", "z2m//floor"):
            with self.subTest(topic=topic), self.assertRaises(ZigbeeMonitorError):
                parse_networks([{"network_id": "a", "base_topic": topic, "name": "One"}])


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.monitor = ZigbeeMonitor(network_configs())

    def test_no_observation_is_not_a_zero_device_count(self):
        self.assertIsNone(self.monitor.total_devices())
        self.assertEqual(self.monitor.network_status("floor_1")["bridge_state"], "unknown")
        self.monitor.ingest("z2m_1/bridge/devices", inventory())
        self.assertIsNone(self.monitor.total_devices())
        self.monitor.ingest("z2m_2/bridge/devices", inventory())
        self.assertEqual(self.monitor.total_devices(), 0)

    def test_coord_not_in_device_roster_and_model_from_definition(self):
        self.monitor.ingest(
            "z2m_1/bridge/devices",
            inventory(device(IEEE3, "Coordinator", "Coordinator"), device()),
            retain=True,
        )
        d = self.monitor.get_device("floor_1", IEEE1)
        self.assertEqual(d.model, "TRV-1")
        self.assertEqual(d.manufacturer, "Vendor")
        self.assertEqual(len(self.monitor.devices("floor_1")), 1)
        self.assertEqual(self.monitor.availability("floor_1", IEEE1), "unknown")

    def test_names_are_for_routing_not_identity(self):
        self.monitor.ingest("z2m_1/bridge/devices", inventory(device(name="Old name")))
        self.monitor.ingest("z2m_1/Old name", b'{"temp":21}', observed_at=120)
        before = self.monitor.get_device("floor_1", IEEE1)
        self.monitor.ingest("z2m_1/bridge/devices", inventory(device(name="New name")))
        after = self.monitor.get_device("floor_1", IEEE1)
        self.assertEqual(before.identity, after.identity)
        self.assertEqual(after.friendly_name, "New name")
        self.assertEqual(self.monitor.ingest("z2m_1/Old name", b"{}").kind, "unmapped_message")
        self.assertTrue(self.monitor.ingest(
            "z2m_1/New name", b'{"temp":22}', observed_at=121,
        ).counted)
        self.assertEqual(self.monitor.counts_snapshot()[(120, "floor_1", IEEE1)], 2)

    def test_topic_with_slash_is_exact_and_retained_replay_not_counted(self):
        self.monitor.ingest("z2m_1/bridge/devices", inventory(device(name="office/heating")))
        packet = self.monitor.ingest(
            "z2m_1/office/heating", b'{"state":"ON"}', observed_at=900,
        )
        self.assertEqual(packet.ieee_address, IEEE1)
        self.assertTrue(packet.counted)
        for topic, kw in [
            ("z2m_1/office/heating", {"retain": True}),
            ("z2m_1/office/heating", {"dup": True}),
            ("z2m_1/office/heating/get", {}),
            ("z2m_1/office/heating/set", {}),
            ("z2m_1/bridge/logging", {}),
            ("z2m_2/office/heating", {}),
            ("z2m_1/unlisted_group", {}),
        ]:
            self.monitor.ingest(topic, b"{}", observed_at=900, **kw)
        self.assertEqual(self.monitor.counts_snapshot(), {(900, "floor_1", IEEE1): 1})

    def test_invalid_inventory_update_does_not_wipe_previous_devices(self):
        self.monitor.ingest("z2m_1/bridge/devices", inventory(device()))
        for bad in (b'not json', b'{}', inventory(device(), device()), inventory({"friendly_name": "no-ieee"})):
            with self.subTest(bad=bad), self.assertRaises(ZigbeeMonitorError):
                self.monitor.ingest("z2m_1/bridge/devices", bad)
            self.assertEqual(len(self.monitor.devices("floor_1")), 1)

    def test_availability_retained_before_inventory_and_reset_on_rename(self):
        early = self.monitor.ingest(
            "z2m_1/bedroom/availability", b'{"state":"offline"}', retain=True
        )
        self.assertEqual(early.kind, "unmapped_availability")
        self.monitor.ingest("z2m_1/bridge/devices", inventory(device()))
        self.assertEqual(self.monitor.availability("floor_1", IEEE1), "offline")
        self.monitor.ingest("z2m_1/bridge/devices", inventory(device(name="New name")))
        self.assertEqual(self.monitor.availability("floor_1", IEEE1), "unknown")
        self.monitor.ingest("z2m_1/New name/availability", b'{"state":"online"}', retain=True)
        self.assertEqual(self.monitor.availability("floor_1", IEEE1), "online")

    def test_broken_availability_is_not_treated_as_offline(self):
        self.monitor.ingest("z2m_1/bridge/devices", inventory(device()))
        for bad in (b"{}", b'{"state":"unavailable"}', b"invalid"):
            with self.subTest(bad=bad), self.assertRaises(ZigbeeMonitorError):
                self.monitor.ingest("z2m_1/bedroom/availability", bad)
            self.assertEqual(self.monitor.availability("floor_1", IEEE1), "unknown")

    def test_bridge_state_plain_and_json(self):
        a = self.monitor.ingest("z2m_1/bridge/state", b"online", retain=True)
        b = self.monitor.ingest("z2m_2/bridge/state", b'{"state":"offline"}', retain=True)
        self.assertEqual(a.kind, "bridge_state")
        self.assertEqual(b.kind, "bridge_state")
        self.assertEqual(self.monitor.network_status("floor_1")["bridge_state"], "online")
        self.assertEqual(self.monitor.network_status("floor_2")["bridge_state"], "offline")
        with self.assertRaises(ZigbeeMonitorError):
            self.monitor.ingest("z2m_1/bridge/state", b"broken")
        self.assertEqual(self.monitor.network_status("floor_1")["bridge_state"], "online")

    def test_multiple_networks_with_same_ieee_are_distinct_observations(self):
        self.monitor.ingest("z2m_1/bridge/devices", inventory(device()))
        self.monitor.ingest("z2m_2/bridge/devices", inventory(device(name="moved")))
        self.monitor.ingest("z2m_1/bedroom", b"{}", observed_at=120)
        self.monitor.ingest("z2m_2/moved", b"{}", observed_at=120)
        self.assertEqual(self.monitor.counts_snapshot(), {
            (120, "floor_1", IEEE1): 1,
            (120, "floor_2", IEEE1): 1,
        })

    def test_acknowledge_only_after_success_and_keep_new_samples(self):
        self.monitor.ingest("z2m_1/bridge/devices", inventory(device()))
        self.monitor.ingest("z2m_1/bedroom", b"{}", observed_at=120)
        old = self.monitor.counts_snapshot()
        self.monitor.ingest("z2m_1/bedroom", b"{}", observed_at=121)
        self.monitor.acknowledge_counts(old)
        self.assertEqual(self.monitor.counts_snapshot(), {(120, "floor_1", IEEE1): 1})
        with self.assertRaises(ZigbeeMonitorError):
            self.monitor.acknowledge_counts({(120, "floor_1", IEEE1): 3})
        self.assertEqual(self.monitor.counts_snapshot(), {(120, "floor_1", IEEE1): 1})

    def test_messages_before_inventory_are_not_attributed(self):
        self.monitor.ingest("z2m_1/bedroom", b"{}", observed_at=120)
        self.assertEqual(self.monitor.counts_snapshot(), {})
        self.monitor.ingest("z2m_1/bridge/devices", inventory(device()))
        self.monitor.ingest("z2m_1/bedroom", b"{}", observed_at=121)
        self.assertEqual(self.monitor.counts_snapshot(), {(120, "floor_1", IEEE1): 1})


if __name__ == "__main__":
    unittest.main()
