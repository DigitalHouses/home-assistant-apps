import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rootfs' / 'app'))

from discovery import STATE_RETAIN, build_discovery_payload


class DiscoveryTests(unittest.TestCase):
    def test_device_discovery_contains_expected_entities(self):
        payload = build_discovery_payload('0.1.2')
        self.assertEqual(payload['device']['identifiers'], ['digitalhouses_db_monitoring'])
        self.assertEqual(payload['device']['name'], 'DH Recorder')
        self.assertEqual(payload['origin']['name'], 'DigitalHouses DB Monitoring')
        self.assertEqual(payload['components']['db_start']['default_entity_id'], 'sensor.dh_db_start')
        self.assertEqual(payload['components']['db_connected']['default_entity_id'], 'binary_sensor.dh_db_connected')
        self.assertEqual(
            payload['components']['recorder_writing']['default_entity_id'],
            'binary_sensor.dh_db_recorder_writing',
        )
        self.assertEqual(payload['components']['db_start']['name'], 'DB start')
        self.assertEqual(payload['components']['db_yesterday_records']['name'], 'DB inserted yesterday')
        self.assertEqual(payload['components']['recorder_writing']['name'], 'DB recorder writing')
        self.assertEqual(payload['components']['db_last_age']['name'], 'DB last age')
        self.assertEqual(len(payload['components']), 13)
        self.assertTrue(STATE_RETAIN)


if __name__ == '__main__':
    unittest.main()

class StorageDiscoveryTests(unittest.TestCase):
    def test_storage_entities_are_included_when_enabled(self):
        payload = build_discovery_payload('0.1.3', include_storage=True)
        components = payload['components']
        self.assertEqual(
            components['db_disk_free']['default_entity_id'],
            'sensor.dh_db_disk_free',
        )
        self.assertEqual(
            components['db_disk_used_percentage']['default_entity_id'],
            'sensor.dh_db_disk_used_percentage',
        )

    def test_storage_entities_are_omitted_when_disabled(self):
        payload = build_discovery_payload('0.1.3', include_storage=False)
        self.assertNotIn('db_disk_free', payload['components'])
        self.assertNotIn('db_disk_used_percentage', payload['components'])
