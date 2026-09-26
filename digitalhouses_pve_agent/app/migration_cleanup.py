from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from .config import AppConfig
from .identity import HostIdentity
from .uninstall_cleanup import _default_client, _publish_retained

log = logging.getLogger(__name__)


def _legacy_discovery_topics(
    config: AppConfig,
    identity: HostIdentity,
) -> tuple[str, ...]:
    prefix = config.mqtt.discovery_prefix.strip("/")
    instance = identity.instance_id
    return (
        f"{prefix}/device/dh_app_pve_{instance}/config",
        f"{prefix}/device/dh_pve_{instance}/config",
        f"{prefix}/device/dh_app_pve_ups_{instance}/config",
        f"{prefix}/device/dh_pve_ups_{instance}/config",
        f"{prefix}/device/dh_ups_{instance}/config",
    )


def cleanup_legacy_mqtt_namespace(
    config: AppConfig,
    identity: HostIdentity,
    *,
    client_factory: Callable[[], Any] | None = None,
    connect_timeout_seconds: float = 5.0,
    scan_seconds: float = 2.0,
) -> bool:
    """Delete retained data owned by one legacy PVE Agent MQTT instance."""

    base = f"{config.mqtt.topic_prefix.rstrip('/')}/{identity.instance_id}"
    topic_filter = f"{base}/#"
    client = (
        client_factory()
        if client_factory is not None
        else _default_client(f"dh_pve_agent_{identity.instance_id}_migration")
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
                rc = result[0] if isinstance(result, tuple) else getattr(result, "rc", result)
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
            *((topic, "") for topic in _legacy_discovery_topics(config, identity)),
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
