from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from .config import AppConfig
from .identity import HostIdentity
from .topics import build_topics, build_ups_topics

log = logging.getLogger(__name__)


def _default_client(client_id: str):
    import paho.mqtt.client as mqtt

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
        if getattr(info, "rc", 1) != 0:
            return False
        info.wait_for_publish(timeout=timeout_seconds)
        is_published = getattr(info, "is_published", None)
        return bool(is_published()) if callable(is_published) else True
    except Exception:
        log.exception("MQTT uninstall cleanup publish failed: %s", topic)
        return False


def cleanup_mqtt(
    config: AppConfig,
    identity: HostIdentity,
    *,
    client_factory: Callable[[], Any] | None = None,
    timeout_seconds: float = 5.0,
    scan_seconds: float = 2.0,
) -> bool:
    """Delete all retained MQTT data owned by one PVE Agent instance."""

    topics = build_topics(config.mqtt, identity)
    ups_topics = build_ups_topics(config.mqtt, identity)
    topic_filter = f"{topics.base}/#"
    client = (
        client_factory()
        if client_factory is not None
        else _default_client(f"{topics.device_id}_uninstall")
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
        if topic != topics.base and not topic.startswith(f"{topics.base}/"):
            return
        with retained_lock:
            retained_topics.add(topic)

    def on_connect(client, userdata, flags, reason_code, properties) -> None:
        nonlocal connection_failed, subscription_failed
        connection_failed = bool(getattr(reason_code, "is_failure", False))
        if not connection_failed:
            try:
                result = client.subscribe(topic_filter, qos=1)
                rc = result[0] if isinstance(result, tuple) else getattr(result, "rc", result)
                subscription_failed = rc not in (None, 0)
            except Exception:
                log.exception("MQTT uninstall cleanup subscribe failed: %s", topic_filter)
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
            log.error("MQTT uninstall cleanup connect returned rc=%s", rc)
            return False

        client.loop_start()
        loop_started = True
        if not connected.wait(timeout_seconds):
            log.error("MQTT uninstall cleanup connection timed out")
            return False
        if connection_failed:
            log.error("MQTT uninstall cleanup connection was rejected")
            return False
        if subscription_failed:
            log.error("MQTT uninstall cleanup subscription failed")
            return False

        if scan_seconds > 0:
            threading.Event().wait(scan_seconds)

        with retained_lock:
            machine_topics = sorted(retained_topics)

        publications = [
            *((topic, "") for topic in machine_topics),
            (topics.availability, ""),
            (ups_topics.availability, ""),
            (topics.discovery, ""),
            (ups_topics.discovery, ""),
            *((topic, "") for topic in topics.legacy_discoveries),
            *((topic, "") for topic in ups_topics.legacy_discoveries),
        ]

        seen: set[str] = set()
        ordered_publications: list[tuple[str, str]] = []
        for topic, payload in publications:
            if topic in seen:
                continue
            seen.add(topic)
            ordered_publications.append((topic, payload))

        ok = True
        for topic, payload in ordered_publications:
            published = _publish_retained(
                client,
                topic,
                payload,
                timeout_seconds=timeout_seconds,
            )
            ok = published and ok
        return ok
    except Exception:
        log.exception("MQTT uninstall cleanup failed before completion")
        return False
    finally:
        try:
            client.disconnect()
        except Exception:
            log.exception("MQTT uninstall cleanup disconnect failed")
        if loop_started:
            try:
                client.loop_stop()
            except Exception:
                log.exception("MQTT uninstall cleanup loop stop failed")
