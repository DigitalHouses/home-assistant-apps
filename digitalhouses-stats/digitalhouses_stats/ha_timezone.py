"""CORE HA's authoritative timezone, transported on the existing local MQTT channel."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Event
from zoneinfo import ZoneInfo

LOG = logging.getLogger(__name__)
TOPIC = "DigitalHouses/Global/ha/timezone/state"


def valid_zone(value):
    if not isinstance(value, str) or not value or len(value) > 128 or value.strip() != value:
        return None
    try:
        return ZoneInfo(value).key
    except (ValueError, KeyError, OSError):
        return None


def cache_path(settings):
    return Path(settings.journal_path).with_name("ha-timezone")


def cached_zone(settings):
    try:
        return valid_zone(cache_path(settings).read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        return None


def zone_metadata(settings):
    zone = cached_zone(settings)
    return {"timezone": zone or "UTC", "timezone_fallback": zone is None}


def cache_zone(settings, value):
    zone = valid_zone(value)
    if zone is None:
        return False
    if zone == cached_zone(settings):
        return True
    path = cache_path(settings)
    temp = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(zone + "\n")
        os.replace(temp, path)
        LOG.info("CORE HA timezone updated: %s", zone)
        return True
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def read_retained_zone():
    """Bounded read on the existing authenticated CORE broker, no new timer."""
    import paho.mqtt.client as mqtt
    received = Event()
    result = []
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect_timeout = 3
    client.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])

    def connected(c, userdata, flags, reason, properties):
        if reason.is_failure:
            received.set()
        else:
            c.subscribe(TOPIC, qos=1)

    def message(c, userdata, msg):
        if msg.topic == TOPIC:
            try:
                zone = valid_zone(msg.payload.decode("utf-8"))
            except UnicodeError:
                zone = None
            if zone is not None:
                result.append(zone)
                received.set()

    client.on_connect = connected
    client.on_message = message
    try:
        client.connect(os.environ["MQTT_HOST"], int(os.getenv("MQTT_PORT", "1883")), keepalive=10)
        client.loop_start()
        received.wait(2)
        return result[0] if result else None
    finally:
        client.disconnect()
        client.loop_stop()


def refresh_zone(settings, read=read_retained_zone):
    # A missing/invalid payload or broker outage never erases a valid cache.
    try:
        return cache_zone(settings, read())
    except Exception:
        LOG.debug("CORE HA timezone refresh unavailable; retaining cached value")
        return False
