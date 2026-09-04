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
    DISCOVERY_TOPIC,
    HA_STATUS_TOPIC,
    STATE_TOPIC,
    build_discovery_payload,
)
from metrics import (
    db_depth_days,
    iso_from_epoch,
    last_age_seconds,
    records_k,
    yesterday_bounds_epoch,
)

APP_VERSION = os.getenv('APP_VERSION', '0.1.0-local')


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
        self.state: dict[str, Any] = {
            'db_connected': False,
            'recorder_writing': False,
        }
        self.state_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.mqtt_connected = threading.Event()
        self.db_available = False
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
        self.publish_json(DISCOVERY_TOPIC, build_discovery_payload(APP_VERSION), retain=True)
        self.publish_text(APP_AVAILABILITY_TOPIC, 'online', retain=True)
        self.publish_text(DB_AVAILABILITY_TOPIC, 'online' if self.db_available else 'offline', retain=True)
        self.publish_state()
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
            self.publish_json(DISCOVERY_TOPIC, build_discovery_payload(APP_VERSION), retain=True)
            self.publish_state()

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
        self.publish_json(STATE_TOPIC, payload, retain=False)

    def update_state(self, values: dict[str, Any]) -> None:
        with self.state_lock:
            self.state.update(values)
        self.publish_state()

    def set_db_available(self, available: bool) -> None:
        self.db_available = available
        self.publish_text(DB_AVAILABILITY_TOPIC, 'online' if available else 'offline', retain=True)

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
            self.update_state(raw)
        except Exception as exc:
            self.log.warning('Static database query failed: %s', exc)

    def run(self) -> None:
        db = self.config.database
        self.log.info('Starting DigitalHouses DB Monitoring %s', APP_VERSION)
        self.log.info('Database engine: %s', db.engine)
        self.log.info('Database target: %s@%s:%s/%s', db.username, db.host, db.port, db.database)
        self.log.info('Timezone: %s', self.config.timezone)

        host = os.environ['MQTT_HOST']
        port = int(os.getenv('MQTT_PORT', '1883'))
        self.client.connect_async(host, port, keepalive=60)
        self.client.loop_start()

        next_fast = next_medium = next_slow = 0.0
        static_loaded = False
        try:
            while not self.stop_event.is_set():
                now_mono = time.monotonic()
                if now_mono >= next_fast:
                    if self.collect_fast() and not static_loaded:
                        self.collect_static()
                        static_loaded = True
                    next_fast = now_mono + self.config.poll.fast_seconds
                if now_mono >= next_medium:
                    self.collect_medium()
                    next_medium = now_mono + self.config.poll.medium_seconds
                if now_mono >= next_slow:
                    self.collect_slow()
                    next_slow = now_mono + self.config.poll.slow_seconds
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
