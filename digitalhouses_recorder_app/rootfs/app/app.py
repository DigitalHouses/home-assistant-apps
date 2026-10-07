from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import paho.mqtt.client as mqtt
from contracts import (
    validate_machine_event,
    validate_release_version,
    validate_runtime_state,
    validate_static_db_metrics,
)
from config import AppConfig, load_config
from db import create_adapter
from discovery import (
    APP_AVAILABILITY_TOPIC,
    DB_AVAILABILITY_TOPIC,
    DB_STATIC_AVAILABILITY_TOPIC,
    DB_STATUS_AVAILABILITY_TOPIC,
    DISCOVERY_TOPIC,
    DISK_USAGE_THRESHOLD_COMMAND_TOPIC,
    DISK_USAGE_THRESHOLD_STATE_TOPIC,
    EVENT_SCHEMA_VERSION,
    EVENT_TOPIC,
    HA_STATUS_TOPIC,
    LEGACY_APP_AVAILABILITY_TOPIC,
    LEGACY_DB_AVAILABILITY_TOPIC,
    LEGACY_DB_STATIC_AVAILABILITY_TOPIC,
    LEGACY_DB_STATUS_AVAILABILITY_TOPIC,
    LEGACY_DISCOVERY_TOPIC,
    LEGACY_DISK_USAGE_THRESHOLD_STATE_TOPIC,
    LEGACY_STATE_TOPIC,
    LEGACY_STORAGE_AVAILABILITY_TOPIC,
    LEGACY_TOP_ENTITIES_24H_TOPIC,
    LEGACY_TOP_ENTITIES_ALL_TIME_TOPIC,
    REFRESH_COMMAND_TOPIC,
    STATE_RETAIN,
    STATE_TOPIC,
    STORAGE_AVAILABILITY_TOPIC,
    TELEMETRY_DELETE_COMMAND_TOPIC,
    TOP_ENTITIES_24H_TOPIC,
    TOP_ENTITIES_ALL_TIME_TOPIC,
    build_discovery_payload,
)
from identity_migration import cleanup_required, mark_cleanup_complete
from storage import StorageCollector
from telemetry import TelemetryClient, TelemetryRunner
from runtime_settings import (
    RuntimeSettingError,
    load_disk_usage_threshold,
    save_disk_usage_threshold,
)
from rankings import (
    TOP_ENTITIES_24H_INTERVAL_SECONDS,
    TOP_ENTITIES_ALL_TIME_INTERVAL_SECONDS,
    build_top_entities_snapshot,
)
from metrics import (
    current_period_starts_epoch,
    db_depth_days,
    iso_from_epoch,
    last_age_seconds,
    previous_hour_bounds_epoch,
    records_k,
    short_db_version,
    yesterday_bounds_epoch,
)
MEDIUM_INTERVAL_SECONDS = 300
SLOW_INTERVAL_SECONDS = 3600
STORAGE_INTERVAL_SECONDS = 300


class DatabaseMonitorApp:
    def __init__(self) -> None:
        self.app_version = validate_release_version(
            os.getenv("APP_VERSION")
        )
        self.started_at = datetime.now(timezone.utc).isoformat()
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
        self.log = logging.getLogger('digitalhouses_recorder_app')
        if not self.config.telemetry_enabled:
            self.log.error(
                "Statistics collection consent not granted. Stopping application."
            )
            raise SystemExit(1)
        self.adapter = create_adapter(self.config.database)
        self.storage = StorageCollector(self.config.storage, self.adapter)
        self.state: dict[str, Any] = {
            "version": self.app_version,
            "started_at": self.started_at,
            "db_type": self.config.database.engine,
        }
        validate_runtime_state(self.state)
        self.state_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.mqtt_connected = threading.Event()
        self.refresh_requested = threading.Event()
        self.refresh_in_progress = threading.Event()
        self.db_available = False
        self.db_status_observed = False
        self.db_static_available = False
        self.storage_available = False
        self._logged_storage_path = ''
        self.ranking_state: dict[str, dict[str, Any]] = {}
        self.disk_usage_threshold_percent = load_disk_usage_threshold()
        self._db_connected_observed: bool | None = None
        self._db_outage_started_epoch: float | None = None
        self._recorder_writing_observed: bool | None = None
        self._storage_problem_observed: bool | None = None
        self.legacy_cleanup_pending = cleanup_required()
        self.legacy_cleanup_in_progress = threading.Event()
        self.telemetry = TelemetryClient(
            enabled=self.config.telemetry_enabled,
            version=self.app_version,
        )
        self.telemetry_runner = TelemetryRunner(self.telemetry)
        self.client = self._build_mqtt_client()

    def _build_mqtt_client(self) -> mqtt.Client:
        client = mqtt.Client(client_id="digitalhouses-recorder-app")
        username = os.getenv('MQTT_USER', '')
        if username:
            client.username_pw_set(username, os.getenv('MQTT_PASSWORD', ''))
        client.will_set(APP_AVAILABILITY_TOPIC, 'offline', qos=1, retain=True)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        return_code,
    ) -> None:
        del userdata, flags
        if return_code != 0:
            self.log.error(
                "MQTT connection failed with code %s",
                return_code,
            )
            return

        self.mqtt_connected.set()
        client.subscribe(HA_STATUS_TOPIC, qos=1)
        client.subscribe(REFRESH_COMMAND_TOPIC, qos=1)
        client.subscribe(
            DISK_USAGE_THRESHOLD_COMMAND_TOPIC,
            qos=1,
        )
        client.subscribe(
            TELEMETRY_DELETE_COMMAND_TOPIC,
            qos=1,
        )
        self.publish_discovery()
        self.publish_text(
            APP_AVAILABILITY_TOPIC,
            "online",
            retain=True,
        )
        self._publish_db_availability()
        self._publish_db_status_availability()
        self._publish_db_static_availability()
        self._publish_storage_availability()
        self.publish_state()
        self.publish_rankings()
        self.publish_disk_usage_threshold()
        self._schedule_legacy_cleanup()
        self.log.info(
            "MQTT connected; canonical discovery published"
        )

    def publish_discovery(self) -> None:
        self.publish_json(
            DISCOVERY_TOPIC,
            build_discovery_payload(
                self.app_version,
                include_storage=self.storage.enabled,
            ),
            retain=True,
        )
    def _schedule_legacy_cleanup(self) -> None:
        if (
            not self.legacy_cleanup_pending
            or self.legacy_cleanup_in_progress.is_set()
        ):
            return
        self.legacy_cleanup_in_progress.set()
        threading.Thread(
            target=self._cleanup_legacy_identity,
            name="dh-recorder-legacy-cleanup",
            daemon=True,
        ).start()

    def _cleanup_legacy_identity(self) -> None:
        retained_topics = (
            LEGACY_STATE_TOPIC,
            LEGACY_TOP_ENTITIES_24H_TOPIC,
            LEGACY_TOP_ENTITIES_ALL_TIME_TOPIC,
            LEGACY_APP_AVAILABILITY_TOPIC,
            LEGACY_DB_AVAILABILITY_TOPIC,
            LEGACY_DB_STATUS_AVAILABILITY_TOPIC,
            LEGACY_DB_STATIC_AVAILABILITY_TOPIC,
            LEGACY_STORAGE_AVAILABILITY_TOPIC,
            LEGACY_DISK_USAGE_THRESHOLD_STATE_TOPIC,
            LEGACY_DISCOVERY_TOPIC,
        )

        try:
            while (
                self.legacy_cleanup_pending
                and self.mqtt_connected.is_set()
                and not self.stop_event.is_set()
            ):
                try:
                    for topic in retained_topics:
                        info = self.client.publish(
                            topic,
                            "",
                            qos=1,
                            retain=True,
                        )
                        if info.rc != mqtt.MQTT_ERR_SUCCESS:
                            raise RuntimeError(
                                "MQTT cleanup publish failed "
                                f"for {topic}: rc={info.rc}"
                            )
                        info.wait_for_publish(timeout=5.0)
                        if not info.is_published():
                            raise RuntimeError(
                                "MQTT cleanup publish was not "
                                f"acknowledged for {topic}"
                            )

                    mark_cleanup_complete(self.app_version)
                    self.legacy_cleanup_pending = False
                    self.log.info(
                        "Legacy HA/MQTT identity cleanup completed"
                    )
                except Exception as exc:
                    self.log.warning(
                        "Legacy HA/MQTT identity cleanup failed; "
                        "will retry while connected: %s",
                        exc,
                    )
                    self.stop_event.wait(60.0)
        finally:
            self.legacy_cleanup_in_progress.clear()

    def _on_disconnect(self, client, userdata, return_code) -> None:
        del client, userdata
        self.mqtt_connected.clear()
        if return_code:
            self.log.warning('MQTT connection lost; reconnect is active')

    def _on_message(
        self,
        client,
        userdata,
        message,
    ) -> None:
        del client, userdata

        threshold_topics = {
            DISK_USAGE_THRESHOLD_COMMAND_TOPIC
        }
        refresh_topics = {REFRESH_COMMAND_TOPIC}

        if message.topic in threshold_topics:
            self._set_disk_usage_threshold(
                message.payload.decode(
                    "utf-8",
                    errors="replace",
                ).strip()
            )
            return

        if message.topic in refresh_topics:
            if (
                self.refresh_requested.is_set()
                or self.refresh_in_progress.is_set()
            ):
                self.log.debug(
                    "Manual full refresh already pending "
                    "or running; duplicate request ignored"
                )
                return
            self.refresh_requested.set()
            self.log.info(
                "Manual full refresh requested"
            )
            return

        if message.topic == TELEMETRY_DELETE_COMMAND_TOPIC:
            threading.Thread(
                target=self._delete_telemetry,
                name="dh-recorder-telemetry-delete",
                daemon=True,
            ).start()
            return

        if message.topic != HA_STATUS_TOPIC:
            return

        payload = message.payload.decode(
            "utf-8",
            errors="replace",
        ).strip().lower()
        if payload == "online":
            self.publish_discovery()
            self._publish_db_availability()
            self._publish_db_status_availability()
            self._publish_db_static_availability()
            self._publish_storage_availability()
            self.publish_state()
            self.publish_rankings()
            self.publish_disk_usage_threshold()

    def _delete_telemetry(self) -> None:
        if self.telemetry.delete():
            self.log.info(
                "Retained DigitalHouses telemetry record deleted"
            )
        else:
            self.log.warning(
                "Unable to delete retained DigitalHouses "
                "telemetry record"
            )

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
        validate_runtime_state(payload)
        self.publish_json(
            STATE_TOPIC,
            payload,
            retain=STATE_RETAIN,
        )

    def publish_rankings(self) -> None:
        topics = {
            "24h": TOP_ENTITIES_24H_TOPIC,
            "all_time": TOP_ENTITIES_ALL_TIME_TOPIC,
        }
        with self.state_lock:
            snapshots = dict(self.ranking_state)
        for period, snapshot in snapshots.items():
            canonical_topic = topics.get(period)
            if canonical_topic is None:
                continue
            self.publish_json(
                canonical_topic,
                snapshot,
                retain=True,
            )

    def publish_disk_usage_threshold(self) -> None:
        payload = f"{self.disk_usage_threshold_percent:g}"
        self.publish_text(
            DISK_USAGE_THRESHOLD_STATE_TOPIC,
            payload,
            retain=True,
        )

    def _observed_at(self, epoch: float | None = None) -> str:
        when = time.time() if epoch is None else epoch
        return datetime.fromtimestamp(
            when,
            ZoneInfo(self.config.timezone),
        ).isoformat(timespec='seconds')

    def _event(
        self,
        event_type: str,
        **data: Any,
    ) -> None:
        payload = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_type": event_type,
            "observed_at": self._observed_at(),
            **data,
        }
        validate_machine_event(payload)
        self.publish_json(
            EVENT_TOPIC,
            payload,
            retain=False,
        )

    def _set_disk_usage_threshold(self, raw_value: str) -> None:
        try:
            updated = save_disk_usage_threshold(raw_value)
        except RuntimeSettingError as exc:
            self.log.warning('Rejected disk usage threshold: %s', exc)
            self.publish_disk_usage_threshold()
            return

        previous = self.disk_usage_threshold_percent
        self.disk_usage_threshold_percent = updated
        self.publish_disk_usage_threshold()
        if updated == previous:
            return

        self.log.info(
            'Disk usage threshold changed: %.1f%% -> %.1f%%',
            previous,
            updated,
        )
        with self.state_lock:
            metrics = {
                key: self.state.get(key)
                for key in (
                    'db_disk_free',
                    'db_disk_used',
                    'db_disk_total',
                    'db_disk_used_percentage',
                )
            }
        if all(value is not None for value in metrics.values()):
            self._observe_storage_problem(metrics, cause='threshold_changed')

    def _observe_db_connection(
        self,
        connected: bool,
        *,
        error: str | None = None,
    ) -> None:
        now = time.time()
        previous = self._db_connected_observed
        self._db_connected_observed = connected

        if previous is None:
            if not connected:
                self._db_outage_started_epoch = now
            return
        if previous == connected:
            return

        if not connected:
            self._db_outage_started_epoch = now
            event_type = 'db_connection_lost'
            payload: dict[str, Any] = {
                'database_engine': self.config.database.engine,
                'database_name': self.config.database.database,
            }
            if error:
                payload['error'] = error
        else:
            event_type = 'db_connection_restored'
            payload = {
                'database_engine': self.config.database.engine,
                'database_name': self.config.database.database,
            }
            if self._db_outage_started_epoch is not None:
                payload['outage_seconds'] = max(
                    0,
                    int(now - self._db_outage_started_epoch),
                )
            self._db_outage_started_epoch = None

        self.publish_state()
        self._event(event_type, **payload)

    def _observe_recorder_writing(
        self,
        writing: bool,
        *,
        last_record_at: str | None,
        last_age_seconds: int | None,
    ) -> None:
        previous = self._recorder_writing_observed
        self._recorder_writing_observed = writing
        if previous is None or previous == writing:
            return

        self.publish_state()
        self._event(
            'recorder_writing_restored' if writing else 'recorder_writing_stopped',
            last_record_at=last_record_at,
            last_age_seconds=last_age_seconds,
            stale_threshold_seconds=self.config.recorder_stale_seconds,
        )

    def _observe_storage_problem(
        self,
        metrics: dict[str, Any],
        *,
        cause: str,
    ) -> None:
        used_percent = float(metrics['db_disk_used_percentage'])
        active = used_percent >= self.disk_usage_threshold_percent
        previous = self._storage_problem_observed
        self._storage_problem_observed = active
        if previous is None or previous == active:
            return

        self.publish_state()
        self._event(
            'storage_usage_high' if active else 'storage_usage_normal',
            used_percent=used_percent,
            used_gb=float(metrics['db_disk_used']),
            free_gb=float(metrics['db_disk_free']),
            total_gb=float(metrics['db_disk_total']),
            threshold_percent=self.disk_usage_threshold_percent,
            cause=cause,
        )

    def update_state(
        self,
        values: dict[str, Any],
    ) -> None:
        with self.state_lock:
            self.state.update(values)

    def _publish_db_availability(self) -> None:
        value = "online" if self.db_available else "offline"
        self.publish_text(
            DB_AVAILABILITY_TOPIC,
            value,
            retain=True,
        )

    def set_db_available(self, available: bool) -> None:
        self.db_available = available
        self._publish_db_availability()

    def _publish_db_status_availability(self) -> None:
        value = (
            "online"
            if self.db_status_observed
            else "offline"
        )
        self.publish_text(
            DB_STATUS_AVAILABILITY_TOPIC,
            value,
            retain=True,
        )

    def set_db_status_observed(
        self,
        observed: bool,
    ) -> None:
        self.db_status_observed = observed
        self._publish_db_status_availability()

    def _publish_db_static_availability(self) -> None:
        value = (
            "online"
            if self.db_static_available
            else "offline"
        )
        self.publish_text(
            DB_STATIC_AVAILABILITY_TOPIC,
            value,
            retain=True,
        )

    def set_db_static_available(
        self,
        available: bool,
    ) -> None:
        self.db_static_available = available
        self._publish_db_static_availability()

    def _publish_storage_availability(self) -> None:
        value = (
            "online"
            if self.storage_available
            else "offline"
        )
        self.publish_text(
            STORAGE_AVAILABILITY_TOPIC,
            value,
            retain=True,
        )

    def set_storage_available(
        self,
        available: bool,
    ) -> None:
        self.storage_available = available
        self._publish_storage_availability()

    def collect_storage(self) -> bool:
        if not self.storage.enabled:
            return True
        try:
            metrics = self.storage.collect()
            self.update_state(metrics)
            if self.config.storage.source == 'ssh':
                resolved_path = self.storage.resolved_path
                if resolved_path and resolved_path != self._logged_storage_path:
                    self.log.info('Storage filesystem path: %s', resolved_path)
                    self._logged_storage_path = resolved_path
            self.set_storage_available(True)
            self._observe_storage_problem(metrics, cause='measurement')
            return True
        except Exception as exc:
            self.log.warning('Storage query failed: %s', exc)
            self.set_storage_available(False)
            return False

    def collect_fast(self) -> bool:
        now = time.time()
        try:
            raw = self.adapter.fast_metrics()
            last_ts = raw.get('db_last_ts')
            age = last_age_seconds(last_ts, now)
            writing = age is not None and age <= self.config.recorder_stale_seconds
            last_record_at = iso_from_epoch(last_ts)
            self.update_state({
                'db_connected': True,
                'db_last': last_record_at,
                'db_last_age': age,
                'recorder_writing': writing,
            })
            self.set_db_available(True)
            self.set_db_status_observed(True)
            self._observe_db_connection(True)
            self._observe_recorder_writing(
                writing,
                last_record_at=last_record_at,
                last_age_seconds=age,
            )
            return True
        except Exception as exc:  # DB driver exceptions differ by backend
            self.log.error('Fast database query failed: %s', exc)
            self.update_state({"db_connected": False})
            self.set_db_available(False)
            self.set_db_status_observed(True)
            self._observe_db_connection(
                False,
                error=str(exc),
            )
            return False

    def collect_medium(self) -> bool:
        now = time.time()
        current_hour_start, today_start = current_period_starts_epoch(
            now,
            self.config.timezone,
        )
        previous_hour_start, previous_hour_end = previous_hour_bounds_epoch(
            now,
            self.config.timezone,
        )
        try:
            raw = self.adapter.medium_metrics(
                now - 3600,
                previous_hour_start,
                previous_hour_end,
                current_hour_start,
                today_start,
                now,
            )
            size = raw.get('db_size_bytes')
            self.update_state({
                'db_records_per_hour': records_k(
                    raw.get('records_last_hour')
                ),
                'db_previous_hour_records': records_k(
                    raw.get('records_previous_hour')
                ),
                'db_current_hour_records': records_k(
                    raw.get('records_current_hour')
                ),
                'db_today_records': records_k(
                    raw.get('records_today')
                ),
                'db_size': (
                    round(float(size) / 1024 / 1024, 1)
                    if size is not None
                    else None
                ),
            })
            return True
        except Exception as exc:
            self.log.warning('Medium database query failed: %s', exc)
            return False

    def collect_slow(self) -> bool:
        now = time.time()
        start_yesterday, start_today = yesterday_bounds_epoch(now, self.config.timezone)
        try:
            raw = self.adapter.slow_metrics(start_yesterday, start_today)
            start_ts = raw.get('db_start_ts')
            self.update_state({
                'db_start': iso_from_epoch(start_ts),
                'db_depth': db_depth_days(start_ts, now, self.config.timezone),
                'db_records': records_k(raw.get('records_total')),
                'db_yesterday_records': records_k(
                    raw.get('records_yesterday')
                ),
            })
            return True
        except Exception as exc:
            self.log.warning('Slow database query failed: %s', exc)
            return False

    def collect_static(self) -> bool:
        try:
            raw = self.adapter.static_metrics()
            raw["db_version"] = short_db_version(
                raw.get("db_version"),
                self.config.database.engine,
            )
            validated = validate_static_db_metrics(raw)
            self.update_state(validated)
            self.set_db_static_available(True)
            return True
        except Exception as exc:
            self.set_db_static_available(False)
            self.log.warning(
                "Static database query failed: %s",
                exc,
            )
            return False

    def collect_top_entities(self, period: str) -> bool:
        generated_ts = time.time()
        since_ts = generated_ts - 86400 if period == '24h' else None
        until_ts = generated_ts if period == '24h' else None
        try:
            rows = self.adapter.top_entities(
                since_ts,
                until_ts,
                self.config.top_entities_limit,
            )
            snapshot = build_top_entities_snapshot(
                rows,
                period,
                generated_ts,
                self.config.timezone,
                self.config.top_entities_limit,
            )
            with self.state_lock:
                self.ranking_state[period] = snapshot
            topic = (
                TOP_ENTITIES_24H_TOPIC
                if period == "24h"
                else TOP_ENTITIES_ALL_TIME_TOPIC
            )
            self.publish_json(topic, snapshot, retain=True)
            return True
        except Exception as exc:
            self.log.warning('Top entities %s query failed: %s', period, exc)
            return False

    def manual_refresh(self) -> None:
        if self.refresh_in_progress.is_set():
            return
        self.refresh_in_progress.set()
        self.refresh_requested.clear()
        self.log.info('Manual full refresh started')
        try:
            db_ok = self.collect_fast()
            refresh_results: list[bool] = [db_ok]
            if db_ok:
                refresh_results.extend([
                    self.collect_static(),
                    self.collect_medium(),
                    self.collect_slow(),
                    self.collect_top_entities('24h'),
                    self.collect_top_entities('all_time'),
                ])
            if self.storage.enabled:
                refresh_results.append(self.collect_storage())
            full_success = all(refresh_results)
            if full_success:
                self.update_state({'db_last_refresh': iso_from_epoch(time.time())})
            self.publish_state()
            if full_success:
                self.log.info('Manual full refresh completed')
            else:
                self.log.warning('Manual full refresh completed with errors')
        finally:
            self.refresh_in_progress.clear()

    def run(self) -> None:
        db = self.config.database
        publish_interval_seconds = self.config.publish_interval_minutes * 60
        self.log.info(
            "Starting DigitalHouses Recorder App %s",
            self.app_version,
        )
        self.log.info('Database engine: %s', db.engine)
        self.log.info(
            "Database target: %s:%s/%s",
            db.host,
            db.port,
            db.database,
        )
        self.log.info('Timezone: %s', self.config.timezone)
        self.log.info(
            'Top entities limit: %s',
            self.config.top_entities_limit,
        )
        self.log.info('Publish interval: %s minute(s)', self.config.publish_interval_minutes)
        self.log.info('Storage monitoring source: %s', self.config.storage.source)
        host = os.environ['MQTT_HOST']
        port = int(os.getenv('MQTT_PORT', '1883'))
        self.client.connect_async(host, port, keepalive=60)
        self.client.loop_start()
        self.telemetry_runner.start()
        next_publish = next_medium = next_slow = next_storage = 0.0
        next_top_24h = next_top_all_time = 0.0
        static_loaded = False
        try:
            while not self.stop_event.is_set():
                now_mono = time.monotonic()
                if self.refresh_requested.is_set():
                    self.manual_refresh()
                if now_mono >= next_publish:
                    db_ok = self.collect_fast()
                    if db_ok:
                        if not static_loaded:
                            static_loaded = self.collect_static()
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
            self.telemetry_runner.stop()
            self.publish_text(
                APP_AVAILABILITY_TOPIC,
                "offline",
                retain=True,
            )
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
