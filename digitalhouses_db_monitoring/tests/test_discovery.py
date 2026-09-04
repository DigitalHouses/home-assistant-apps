import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rootfs' / 'app'))

from discovery import build_discovery_payload

class DiscoveryTests(unittest.TestCase):
    def test_device_discovery_contains_expected_entities(self):
        payload = build_discovery_payload('0.1.0')
        self.assertEqual(payload['device']['identifiers'], ['digitalhouses_db_monitoring'])
        self.assertEqual(payload['origin']['name'], 'DigitalHouses DB Monitoring')
        self.assertEqual(payload['components']['db_start']['default_entity_id'], 'sensor.dh_db_start')
        self.assertEqual(payload['components']['db_connected']['default_entity_id'], 'binary_sensor.dh_db_connected')
        self.assertEqual(len(payload['components']), 13)

if __name__ == '__main__':
    unittest.main()
