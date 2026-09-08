import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rootfs' / 'app'))

from discovery import REFRESH_COMMAND_TOPIC, STATE_RETAIN, build_discovery_payload


class DiscoveryTests(unittest.TestCase):
    def test_device_discovery_contains_expected_entities(self):
        payload = build_discovery_payload('0.1.7')
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
        self.assertEqual(len(payload['components']), 16)
        self.assertTrue(STATE_RETAIN)


class StorageDiscoveryTests(unittest.TestCase):
    def test_storage_entities_are_included_when_enabled(self):
        payload = build_discovery_payload('0.1.7', include_storage=True)
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
        payload = build_discovery_payload('0.1.7', include_storage=False)
        self.assertNotIn('db_disk_free', payload['components'])
        self.assertNotIn('db_disk_used_percentage', payload['components'])


class RankingDiscoveryTests(unittest.TestCase):
    def test_ranking_entities_include_json_attributes(self):
        payload = build_discovery_payload('0.1.7')
        components = payload['components']
        for key, entity_id in (
            ('db_top_entities_24h', 'sensor.dh_db_top_entities_24h'),
            ('db_top_entities_all_time', 'sensor.dh_db_top_entities_all_time'),
        ):
            component = components[key]
            self.assertEqual(component['default_entity_id'], entity_id)
            self.assertEqual(component['state_topic'], component['json_attributes_topic'])
            self.assertNotEqual(component['state_topic'], 'DigitalHouses/Global/db_monitoring/state')
            self.assertEqual(component['value_template'], '{{ value_json.top_records }}')
            self.assertEqual(component['json_attributes_template'], '{{ value_json | tojson }}')


class RefreshDiscoveryTests(unittest.TestCase):
    def test_refresh_button_is_exposed_by_mqtt_discovery(self):
        payload = build_discovery_payload('0.1.7')
        component = payload['components']['db_refresh']

        self.assertEqual(component['platform'], 'button')
        self.assertEqual(component['default_entity_id'], 'button.dh_db_refresh')
        self.assertEqual(component['command_topic'], REFRESH_COMMAND_TOPIC)
        self.assertEqual(component['payload_press'], 'PRESS')
        self.assertEqual(component['entity_category'], 'diagnostic')
        self.assertNotIn('state_topic', component)
        self.assertNotIn('value_template', component)


if __name__ == '__main__':
    unittest.main()
