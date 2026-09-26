from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from .config import AppConfig

log = logging.getLogger(__name__)


def legacy_base_topic(config: AppConfig) -> str:
    prefix = config.mqtt.topic_prefix.rstrip("/")
    instance = config.general.instance_id
    return prefix if instance == "plex" else f"{prefix}/{instance}"


def legacy_discovery_topic(config: AppConfig) -> str:
    prefix = config.mqtt.discovery_prefix.strip("/")
    return (
        f"{prefix}/device/"
        f"digitalhouses_plex_monitoring_{config.general.instance_id}/config"
    )


def _default_client(client_id: str) -> mqtt.Client:
    return mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
    )


def _publish_retained(
    client: Any,
    topic: str,
    payload: str,
    *,
    timeout_seconds: float,
) -> bool:
    try:
        info = client.publish(topic, payload=payload, qos=1, retain=True)
        if hasattr(info, "wait_for_publish"):
            info.wait_for_publish(timeout=timeout_seconds)
        rc = getattr(info, "rc", mqtt.MQTT_ERR_SUCCESS)
        return rc == mqtt.MQTT_ERR_SUCCESS
    except Exception:
        log.exception("MQTT migration cleanup publish failed: %s", topic)
        return False


def cleanup_legacy_mqtt_namespace(
    config: AppConfig,
    *,
    client_factory: Callable[[], Any] | None = None,
    connect_timeout_seconds: float = 5.0,
    scan_seconds: float = 2.0,
) -> bool:
    """Delete retained state and Discovery owned by one legacy Plex instance."""

    base = legacy_base_topic(config)
    topic_filter = f"{base}/#"
    client = (
        client_factory()
        if client_factory is not None
        else _default_client(
            f"dh_plex_agent_{config.general.instance_id}_migration"
        )
    )

    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)

    connected = threading.Event()
    retained_lock = threading.Lock()
    retained_topics: set[str] = set()
    connection_failed = False
    subscription_failed = False

    def on_message(client, userdata, message) -> None:
        if not bool(getattr(message, "retain", False)):
            return
        topic = str(getattr(message, "topic", ""))
        if topic != base and not topic.startswith(f"{base}/"):
            return
        with retained_lock:
            retained_topics.add(topic)

    def on_connect(client, userdata, flags, reason_code, properties) -> None:
        nonlocal connection_failed, subscription_failed
        connection_failed = bool(getattr(reason_code, "is_failure", False))
        if not connection_failed:
            try:
                result = client.subscribe(topic_filter, qos=1)
                rc = (
                    result[0]
                    if isinstance(result, tuple)
                    else getattr(result, "rc", result)
                )
                subscription_failed = rc not in (None, 0)
            except Exception:
                log.exception(
                    "MQTT migration cleanup subscribe failed: %s",
                    topic_filter,
                )
                subscription_failed = True
        connected.set()

    client.on_message = on_message
    client.on_connect = on_connect

    loop_started = False
    try:
        rc = client.connect(
            config.mqtt.host,
            config.mqtt.port,
            config.mqtt.keepalive_seconds,
        )
        if rc not in (None, 0):
            log.error("MQTT migration cleanup connect returned rc=%s", rc)
            return False

        client.loop_start()
        loop_started = True

        if not connected.wait(connect_timeout_seconds):
            log.error("MQTT migration cleanup connection timed out")
            return False
        if connection_failed:
            log.error("MQTT migration cleanup connection was rejected")
            return False
        if subscription_failed:
            log.error("MQTT migration cleanup subscription failed")
            return False

        if scan_seconds > 0:
            threading.Event().wait(scan_seconds)

        with retained_lock:
            machine_topics = sorted(retained_topics)

        publications = [
            *((topic, "") for topic in machine_topics),
            (legacy_discovery_topic(config), ""),
        ]

        ok = True
        for topic, payload in publications:
            published = _publish_retained(
                client,
                topic,
                payload,
                timeout_seconds=connect_timeout_seconds,
            )
            ok = published and ok
        return ok
    except Exception:
        log.exception("MQTT migration cleanup failed before completion")
        return False
    finally:
        try:
            client.disconnect()
        except Exception:
            log.exception("MQTT migration cleanup disconnect failed")
        if loop_started:
            try:
                client.loop_stop()
            except Exception:
                log.exception("MQTT migration cleanup loop stop failed")
