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
    metrics.iso_from_epoch = lambda value: (
        '2026-09-26T07:00:00Z' if value is not None else None
    )
    metrics.last_age_seconds = lambda last_ts, now: (
        None if last_ts is None else max(0, int(now - last_ts))
    )
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
        'digitalhouses_recorder_app_events_test',
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


class RecorderEventTests(unittest.TestCase):
    def make_app(self):
        app = DatabaseMonitorApp.__new__(DatabaseMonitorApp)
        app.log = logging.getLogger('test')
        app.state = {}
        app.state_lock = threading.RLock()
        app.publish_state = Mock()
        app._event = Mock()
        app.disk_usage_threshold_percent = 80.0
        app._db_connected_observed = None
        app._db_outage_started_epoch = None
        app._recorder_writing_observed = None
        app._storage_problem_observed = None
        app.config = types.SimpleNamespace(
            timezone='Asia/Almaty',
            recorder_stale_seconds=300,
            database=types.SimpleNamespace(
                engine='postgresql',
                database='homeassistant',
            ),
        )
        return app

    def test_initial_db_observation_only_establishes_baseline(self):
        app = self.make_app()

        app._observe_db_connection(True)

        app._event.assert_not_called()

    def test_db_loss_and_restore_emit_machine_events(self):
        app = self.make_app()

        with patch.object(APP_MODULE.time, 'time', side_effect=[1000.0, 1012.0, 1042.0]):
            app._observe_db_connection(True)
            app._observe_db_connection(False, error='connection refused')
            app._observe_db_connection(True)

        self.assertEqual(app._event.call_count, 2)
        lost = app._event.call_args_list[0]
        restored = app._event.call_args_list[1]
        self.assertEqual(lost.args[0], 'db_connection_lost')
        self.assertEqual(lost.kwargs['database_name'], 'homeassistant')
        self.assertEqual(lost.kwargs['error'], 'connection refused')
        self.assertEqual(restored.args[0], 'db_connection_restored')
        self.assertEqual(restored.kwargs['outage_seconds'], 30)

    def test_recorder_writing_transition_contains_event_snapshot(self):
        app = self.make_app()

        app._observe_recorder_writing(
            True,
            last_record_at='2026-09-26T07:00:00Z',
            last_age_seconds=5,
        )
        app._observe_recorder_writing(
            False,
            last_record_at='2026-09-26T07:00:00Z',
            last_age_seconds=301,
        )

        app._event.assert_called_once_with(
            'recorder_writing_stopped',
            last_record_at='2026-09-26T07:00:00Z',
            last_age_seconds=301,
            stale_threshold_seconds=300,
        )

    def test_storage_threshold_transition_contains_measurements(self):
        app = self.make_app()
        normal = {
            'db_disk_used_percentage': 79.0,
            'db_disk_used': 79.0,
            'db_disk_free': 21.0,
            'db_disk_total': 100.0,
        }
        high = {
            'db_disk_used_percentage': 81.0,
            'db_disk_used': 81.0,
            'db_disk_free': 19.0,
            'db_disk_total': 100.0,
        }

        app._observe_storage_problem(normal, cause='measurement')
        app._observe_storage_problem(high, cause='measurement')

        app._event.assert_called_once_with(
            'storage_usage_high',
            used_percent=81.0,
            used_gb=81.0,
            free_gb=19.0,
            total_gb=100.0,
            threshold_percent=80.0,
            cause='measurement',
        )

    def test_threshold_change_can_create_storage_transition(self):
        app = self.make_app()
        app.state = {
            'db_disk_used_percentage': 75.0,
            'db_disk_used': 75.0,
            'db_disk_free': 25.0,
            'db_disk_total': 100.0,
        }
        app._storage_problem_observed = False
        app.publish_disk_usage_threshold = Mock()

        with patch.object(
            APP_MODULE,
            'save_disk_usage_threshold',
            return_value=70.0,
        ):
            app._set_disk_usage_threshold('70')

        self.assertEqual(app.disk_usage_threshold_percent, 70.0)
        app._event.assert_called_once_with(
            'storage_usage_high',
            used_percent=75.0,
            used_gb=75.0,
            free_gb=25.0,
            total_gb=100.0,
            threshold_percent=70.0,
            cause='threshold_changed',
        )


if __name__ == '__main__':
    unittest.main()
