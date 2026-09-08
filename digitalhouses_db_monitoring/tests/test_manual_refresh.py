import importlib.util
import logging
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

APP_DIR = Path(__file__).resolve().parents[1] / 'rootfs' / 'app'
sys.path.insert(0, str(APP_DIR))

from discovery import REFRESH_COMMAND_TOPIC


def load_app_module():
    paho = types.ModuleType('paho')
    paho_mqtt = types.ModuleType('paho.mqtt')
    paho_client = types.ModuleType('paho.mqtt.client')
    paho_client.Client = object
    paho_client.MQTT_ERR_SUCCESS = 0
    paho.mqtt = paho_mqtt
    paho_mqtt.client = paho_client

    config = types.ModuleType('config')
    config.AppConfig = object
    config.load_config = lambda: None

    db = types.ModuleType('db')
    db.create_adapter = lambda *_args, **_kwargs: None

    storage = types.ModuleType('storage')
    storage.StorageCollector = object

    rankings = types.ModuleType('rankings')
    rankings.TOP_ENTITIES_24H_INTERVAL_SECONDS = 3600
    rankings.TOP_ENTITIES_ALL_TIME_INTERVAL_SECONDS = 86400
    rankings.build_top_entities_snapshot = lambda *args, **kwargs: {}

    metrics = types.ModuleType('metrics')
    metrics.db_depth_days = lambda *args, **kwargs: None
    metrics.iso_from_epoch = lambda *args, **kwargs: None
    metrics.last_age_seconds = lambda *args, **kwargs: None
    metrics.records_k = lambda *args, **kwargs: None
    metrics.short_db_version = lambda *args, **kwargs: None
    metrics.yesterday_bounds_epoch = lambda *args, **kwargs: (0, 0)

    stubs = {
        'paho': paho,
        'paho.mqtt': paho_mqtt,
        'paho.mqtt.client': paho_client,
        'config': config,
        'db': db,
        'storage': storage,
        'rankings': rankings,
        'metrics': metrics,
    }

    spec = importlib.util.spec_from_file_location(
        'digitalhouses_db_monitoring_app_manual_refresh_test',
        APP_DIR / 'app.py',
    )
    if spec is None or spec.loader is None:
        raise RuntimeError('Unable to load app.py for test')
    module = importlib.util.module_from_spec(spec)

    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


APP_MODULE = load_app_module()
DatabaseMonitorApp = APP_MODULE.DatabaseMonitorApp


class Message:
    def __init__(self, topic, payload=b'PRESS'):
        self.topic = topic
        self.payload = payload


class ManualRefreshTests(unittest.TestCase):
    def make_app(self):
        app = DatabaseMonitorApp.__new__(DatabaseMonitorApp)
        app.log = logging.getLogger('test')
        app.refresh_requested = threading.Event()
        app.refresh_in_progress = threading.Event()
        app.storage = types.SimpleNamespace(enabled=True)
        app.collect_fast = Mock(return_value=True)
        app.collect_static = Mock(return_value=True)
        app.collect_medium = Mock(return_value=True)
        app.collect_slow = Mock(return_value=True)
        app.collect_top_entities = Mock(return_value=True)
        app.collect_storage = Mock(return_value=True)
        app.publish_state = Mock()
        app.update_state = Mock()
        return app

    def test_refresh_command_queues_manual_refresh(self):
        app = self.make_app()

        app._on_message(None, None, Message(REFRESH_COMMAND_TOPIC))

        self.assertTrue(app.refresh_requested.is_set())

    def test_refresh_command_is_ignored_while_refresh_is_in_progress(self):
        app = self.make_app()
        app.refresh_in_progress.set()

        app._on_message(None, None, Message(REFRESH_COMMAND_TOPIC))

        self.assertFalse(app.refresh_requested.is_set())

    def test_on_connect_subscribes_to_refresh_command_topic(self):
        app = self.make_app()
        app.mqtt_connected = threading.Event()
        app.db_available = True
        app.storage_available = True
        app.storage = types.SimpleNamespace(enabled=False)
        app.publish_json = Mock()
        app.publish_text = Mock()
        app.publish_rankings = Mock()
        client = Mock()

        app._on_connect(client, None, None, 0)

        client.subscribe.assert_any_call(REFRESH_COMMAND_TOPIC, qos=1)

    def test_run_processes_pending_manual_refresh(self):
        app = self.make_app()
        app.config = types.SimpleNamespace(
            database=types.SimpleNamespace(
                engine='postgresql',
                username='user',
                host='db',
                port=5432,
                database='ha',
            ),
            publish_interval_minutes=1,
            timezone='Asia/Almaty',
            storage=types.SimpleNamespace(source='disabled'),
        )
        app.client = Mock()
        app.stop_event = threading.Event()
        app.manual_refresh = Mock()
        app.refresh_requested.set()
        app.collect_fast = Mock(side_effect=lambda: app.stop_event.set() or False)
        app.publish_text = Mock()

        with patch.dict('os.environ', {'MQTT_HOST': 'mqtt'}):
            app.run()

        app.manual_refresh.assert_called_once_with()

    def test_manual_refresh_collects_all_groups_and_publishes_state(self):
        app = self.make_app()

        app.manual_refresh()

        app.collect_fast.assert_called_once_with()
        app.collect_static.assert_called_once_with()
        app.collect_medium.assert_called_once_with()
        app.collect_slow.assert_called_once_with()
        app.collect_top_entities.assert_any_call('24h')
        app.collect_top_entities.assert_any_call('all_time')
        self.assertEqual(app.collect_top_entities.call_count, 2)
        app.collect_storage.assert_called_once_with()
        app.publish_state.assert_called_once_with()

    def test_successful_manual_refresh_updates_last_refresh_timestamp(self):
        app = self.make_app()

        with patch.object(APP_MODULE.time, 'time', return_value=1788876000), patch.object(
            APP_MODULE, 'iso_from_epoch', return_value='2026-09-08T12:00:00+00:00'
        ):
            app.manual_refresh()

        app.update_state.assert_called_once_with({
            'db_last_refresh': '2026-09-08T12:00:00+00:00'
        })

    def test_failed_manual_refresh_does_not_update_last_refresh_timestamp(self):
        app = self.make_app()
        app.collect_slow.return_value = False

        app.manual_refresh()

        app.update_state.assert_not_called()


if __name__ == '__main__':
    unittest.main()
