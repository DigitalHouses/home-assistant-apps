from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import paho.mqtt.client as mqtt

from config import AppConfig, load_config
from db import create_adapter
from discovery import (
    APP_AVAILABILITY_TOPIC,
    DB_AVAILABILITY_TOPIC,
    STORAGE_AVAILABILITY_TOPIC,
    DISCOVERY_TOPIC,
    HA_STATUS_TOPIC,
    STATE_RETAIN,
    STATE_TOPIC,
    TOP_ENTITIES_24H_TOPIC,
    TOP_ENTITIES_ALL_TIME_TOPIC,
    build_discovery_payload,
)
from storage import StorageCollector
from rankings import (
    TOP_ENTITIES_24H_INTERVAL_SECONDS,
    TOP_ENTITIES_ALL_TIME_INTERVAL_SECONDS,
    build_top_entities_snapshot,
)
from metrics import (
    db_depth_days,
    iso_from_epoch,
    last_age_seconds,
    records_k,
    short_db_version,
    yesterday_bounds_epoch,
)

APP_VERSION = os.getenv('APP_VERSION', '0.1.6-local')
MEDIUM_INTERVAL_SECONDS = 300
SLOW_INTERVAL_SECONDS = 3600
STORAGE_INTERVAL_SECONDS = 300


class DatabaseMonitorApp:
    def __init__(self) -> None:
        self.config: AppConfig = load_config()
        try:
            ZoneInfo(self.config.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f'Unknown timezone: {self.config.timezone}') from exc

        logging.basicConfig(
            level=getattr(logging, self.config.log_level.upper()),
            format='%(asctime)s %(levelname)s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
        self.log = logging.getLogger('digitalhouses_db_monitoring')
        self.adapter = create_adapter(self.config.database)
        self.storage = StorageCollector(self.config.storage, self.adapter)
        self.state: dict[str, Any] = {
            'db_connected': False,
            'recorder_writing': False,
        }
        self.state_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.mqtt_connected = threading.Event()
        self.db_available = False
        self.storage_available = False
        self._logged_storage_path = ''
        self.ranking_state: dict[str, dict[str, Any]] = {}
        self.client = self._build_mqtt_client()

    def _build_mqtt_client(self) -> mqtt.Client:
        client = mqtt.Client(client_id='digitalhouses-db-monitoring')
        username = os.getenv('MQTT_USER', '')
        if username:
            client.username_pw_set(username, os.getenv('MQTT_PASSWORD', ''))
        client.will_set(APP_AVAILABILITY_TOPIC, 'offline', qos=1, retain=True)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    def _on_connect(self, client, userdata, flags, return_code) -> None:
        del userdata, flags
        if return_code != 0:
            self.log.error('MQTT connection failed with code %s', return_code)
            return
        self.mqtt_connected.set()
        client.subscribe(HA_STATUS_TOPIC, qos=1)
        self.publish_json(
            DISCOVERY_TOPIC,
            build_discovery_payload(APP_VERSION, include_storage=self.storage.enabled),
            retain=True,
        )
        self.publish_text(APP_AVAILABILITY_TOPIC, 'online', retain=True)
        self.publish_text(DB_AVAILABILITY_TOPIC, 'online' if self.db_available else 'offline', retain=True)
        self.publish_text(
            STORAGE_AVAILABILITY_TOPIC,
            'online' if self.storage_available else 'offline',
            retain=True,
        )
        self.publish_state()
        self.publish_rankings()
        self.log.info('MQTT connected; discovery published')

    def _on_disconnect(self, client, userdata, return_code) -> None:
        del client, userdata
        self.mqtt_connected.clear()
        if return_code:
            self.log.warning('MQTT connection lost; reconnect is active')

    def _on_message(self, client, userdata, message) -> None:
        del client, userdata
        if message.topic != HA_STATUS_TOPIC:
            return
        payload = message.payload.decode('utf-8', errors='replace').strip().lower()
        if payload == 'online':
            self.publish_json(
                DISCOVERY_TOPIC,
                build_discovery_payload(APP_VERSION, include_storage=self.storage.enabled),
                retain=True,
            )
            self.publish_state()
            self.publish_rankings()

    def publish_text(self, topic: str, payload: str, retain: bool) -> None:
        if not self.mqtt_connected.is_set():
            return
        info = self.client.publish(topic, payload, qos=1, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            self.log.warning('MQTT publish failed for %s: rc=%s', topic, info.rc)

    def publish_json(self, topic: str, payload: dict[str, Any], retain: bool = False) -> None:
        self.publish_text(
            topic,
            json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
            retain,
        )

    def publish_state(self) -> None:
        with self.state_lock:
            payload = dict(self.state)
        self.publish_json(STATE_TOPIC, payload, retain=STATE_RETAIN)

    def publish_rankings(self) -> None:
        topics = {
            '24h': TOP_ENTITIES_24H_TOPIC,
            'all_time': TOP_ENTITIES_ALL_TIME_TOPIC,
        }
        with self.state_lock:
            snapshots = dict(self.ranking_state)
        for period, snapshot in snapshots.items():
            topic = topics.get(period)
            if topic:
                self.publish_json(topic, snapshot, retain=True)

    def update_state(self, values: dict[str, Any]) -> None:
        with self.state_lock:
            self.state.update(values)

    def set_db_available(self, available: bool) -> None:
        self.db_available = available
        self.publish_text(DB_AVAILABILITY_TOPIC, 'online' if available else 'offline', retain=True)

    def set_storage_available(self, available: bool) -> None:
        self.storage_available = available
        self.publish_text(
            STORAGE_AVAILABILITY_TOPIC,
            'online' if available else 'offline',
            retain=True,
        )

    def collect_storage(self) -> None:
        if not self.storage.enabled:
            return
        try:
            self.update_state(self.storage.collect())
            if self.config.storage.source == 'ssh':
                resolved_path = self.storage.resolved_path
                if resolved_path and resolved_path != self._logged_storage_path:
                    self.log.info('Storage filesystem path: %s', resolved_path)
                    self._logged_storage_path = resolved_path
            self.set_storage_available(True)
        except Exception as exc:
            self.log.warning('Storage query failed: %s', exc)
            self.set_storage_available(False)

    def collect_fast(self) -> bool:
        now = time.time()
        try:
            raw = self.adapter.fast_metrics()
            last_ts = raw.get('db_last_ts')
            age = last_age_seconds(last_ts, now)
            writing = age is not None and age <= self.config.recorder_stale_seconds
            self.update_state({
                'db_connected': True,
                'db_last': iso_from_epoch(last_ts),
                'db_last_age': age,
                'recorder_writing': writing,
            })
            self.set_db_available(True)
            return True
        except Exception as exc:  # DB driver exceptions differ by backend
            self.log.error('Fast database query failed: %s', exc)
            self.update_state({'db_connected': False, 'recorder_writing': False})
            self.set_db_available(False)
            return False

    def collect_medium(self) -> None:
        now = time.time()
        try:
            raw = self.adapter.medium_metrics(now - 3600)
            size = raw.get('db_size_bytes')
            self.update_state({
                'db_records_per_hour': records_k(raw.get('records_last_hour')),
                'db_size': round(float(size) / 1024 / 1024, 1) if size is not None else None,
            })
        except Exception as exc:
            self.log.warning('Medium database query failed: %s', exc)

    def collect_slow(self) -> None:
        now = time.time()
        start_yesterday, start_today = yesterday_bounds_epoch(now, self.config.timezone)
        try:
            raw = self.adapter.slow_metrics(start_yesterday, start_today)
            start_ts = raw.get('db_start_ts')
            self.update_state({
                'db_start': iso_from_epoch(start_ts),
                'db_depth': db_depth_days(start_ts, now, self.config.timezone),
                'db_records': records_k(raw.get('records_total')),
                'db_yesterday_records': raw.get('records_yesterday'),
            })
        except Exception as exc:
            self.log.warning('Slow database query failed: %s', exc)

    def collect_static(self) -> None:
        try:
            raw = self.adapter.static_metrics()
            raw['db_version'] = short_db_version(raw.get('db_version'), self.config.database.engine)
            self.update_state(raw)
        except Exception as exc:
            self.log.warning('Static database query failed: %s', exc)

    def collect_top_entities(self, period: str) -> None:
        generated_ts = time.time()
        since_ts = generated_ts - 86400 if period == '24h' else None
        try:
            rows = self.adapter.top_entities(since_ts)
            snapshot = build_top_entities_snapshot(
                rows, period, generated_ts, self.config.timezone
            )
            with self.state_lock:
                self.ranking_state[period] = snapshot
            topic = TOP_ENTITIES_24H_TOPIC if period == '24h' else TOP_ENTITIES_ALL_TIME_TOPIC
            self.publish_json(topic, snapshot, retain=True)
        except Exception as exc:
            self.log.warning('Top entities %s query failed: %s', period, exc)

    def run(self) -> None:
        db = self.config.database
        publish_interval_seconds = self.config.publish_interval_minutes * 60

        self.log.info('Starting DigitalHouses DB Monitoring %s', APP_VERSION)
        self.log.info('Database engine: %s', db.engine)
        self.log.info('Database target: %s@%s:%s/%s', db.username, db.host, db.port, db.database)
        self.log.info('Timezone: %s', self.config.timezone)
        self.log.info('Publish interval: %s minute(s)', self.config.publish_interval_minutes)
        self.log.info('Storage monitoring source: %s', self.config.storage.source)

        host = os.environ['MQTT_HOST']
        port = int(os.getenv('MQTT_PORT', '1883'))
        self.client.connect_async(host, port, keepalive=60)
        self.client.loop_start()

        next_publish = next_medium = next_slow = next_storage = 0.0
        next_top_24h = next_top_all_time = 0.0
        static_loaded = False
        try:
            while not self.stop_event.is_set():
                now_mono = time.monotonic()
                if now_mono >= next_publish:
                    db_ok = self.collect_fast()
                    if db_ok:
                        if not static_loaded:
                            self.collect_static()
                            static_loaded = True
                        if now_mono >= next_medium:
                            self.collect_medium()
                            next_medium = now_mono + MEDIUM_INTERVAL_SECONDS
                        if now_mono >= next_slow:
                            self.collect_slow()
                            next_slow = now_mono + SLOW_INTERVAL_SECONDS
                        if now_mono >= next_top_24h:
                            self.collect_top_entities('24h')
                            next_top_24h = now_mono + TOP_ENTITIES_24H_INTERVAL_SECONDS
                        if now_mono >= next_top_all_time:
                            self.collect_top_entities('all_time')
                            next_top_all_time = now_mono + TOP_ENTITIES_ALL_TIME_INTERVAL_SECONDS
                    if self.storage.enabled and now_mono >= next_storage:
                        self.collect_storage()
                        next_storage = now_mono + STORAGE_INTERVAL_SECONDS
                    self.publish_state()
                    next_publish = now_mono + publish_interval_seconds
                self.stop_event.wait(1.0)
        finally:
            self.publish_text(APP_AVAILABILITY_TOPIC, 'offline', retain=True)
            self.client.disconnect()
            self.client.loop_stop()

    def stop(self, *_args) -> None:
        self.stop_event.set()


def main() -> None:
    app = DatabaseMonitorApp()
    signal.signal(signal.SIGTERM, app.stop)
    signal.signal(signal.SIGINT, app.stop)
    app.run()


if __name__ == '__main__':
    main()
