"""Standalone MQTT runtime for the domain core; HA Core is not required."""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
import logging
import os
import signal
import time

import paho.mqtt.client as mqtt

from core import ContractError, Engine, GLOBAL, PRODUCT, Store

LOG = logging.getLogger("system_globals")
COMMANDS = (GLOBAL + "/set", PRODUCT + "/config/set", PRODUCT + "/profiles/set")


class TransportError(RuntimeError):
    pass


class Session:
    """One MQTT connection; never reconnect an old client with queued events."""
    def __init__(self, host, port, username, password):
        self.host, self.port = host, port
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  protocol=mqtt.MQTTv5, reconnect_on_failure=False)
        self.client.connect_timeout = 5.0
        if username is not None:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_subscribe = self.on_subscribe
        self.client.on_message = self.on_message
        self.client.on_publish = self.on_publish
        self.publish_results = {}
        self.pending = set()
        self.messages = deque()
        self.connected = False
        self.failed = False

    def on_connect(self, client, userdata, flags, reason, properties):
        if reason.is_failure:
            self.failed = True
            return
        for topic in COMMANDS:
            # MQTT5 preserves the sender's retain flag and skips old retained commands.
            rc, mid = client.subscribe(topic, options=mqtt.SubscribeOptions(
                qos=1, retainAsPublished=True, retainHandling=2))
            if rc != mqtt.MQTT_ERR_SUCCESS:
                self.failed = True
                return
            self.pending.add(mid)
        self.connected = True

    def on_disconnect(self, client, userdata, flags, reason, properties):
        self.failed = True

    def on_subscribe(self, client, userdata, mid, reasons, properties):
        if any(r.is_failure for r in reasons):
            self.failed = True
        self.pending.discard(mid)

    def on_publish(self, client, userdata, mid, reason, properties):
        self.publish_results[mid] = reason

    def on_message(self, client, userdata, message):
        if len(self.messages) >= 256:
            self.failed = True
            return
        self.messages.append((message.topic, message.payload, message.retain))

    def pump(self, timeout=0.2):
        if self.failed or self.client.loop(timeout=timeout) != mqtt.MQTT_ERR_SUCCESS or self.failed:
            raise TransportError("MQTT connection lost")

    def await_condition(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise TransportError("MQTT acknowledgement timeout")
            self.pump()
        if self.failed:
            raise TransportError("MQTT connection lost")

    def open(self):
        rc = self.client.connect(self.host, self.port, keepalive=15, clean_start=True)
        if rc != mqtt.MQTT_ERR_SUCCESS:
            raise TransportError("MQTT connect failed")
        self.await_condition(lambda: self.connected and not self.pending)

    def publish(self, publications):
        for msg in publications:
            info = self.client.publish(msg.topic, msg.wire(), qos=msg.qos, retain=msg.retain)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise TransportError("MQTT publish failed")
            # State PUBACK precedes publishing its transient event.
            self.await_condition(lambda: info.mid in self.publish_results)
            if self.publish_results.pop(info.mid).is_failure:
                raise TransportError("Broker rejected publication")

    def close(self):
        self.client.disconnect()
        try:
            self.client.loop(timeout=0.1)
        except OSError:
            pass


def now():
    return datetime.now(timezone.utc)


def apply_message(engine, session, topic, raw, retained):
    try:
        value = raw.decode("utf-8")
        if topic != GLOBAL + "/set":
            value = json.loads(value)
        publications = engine.command(topic, value, now(), retained=retained)
    except (ContractError, UnicodeError, json.JSONDecodeError):
        LOG.warning("Rejected invalid command on %s", topic)
        return
    session.publish(publications)


def run(engine, host, port, username, password, stopped):
    while not stopped():
        # Apply elapsed boundaries locally even while MQTT is unavailable.
        # No historical event replay on reconnect.
        engine.tick(now())
        session = Session(host, port, username, password)
        try:
            session.open()
            engine.tick(now())
            session.publish(engine.snapshot())
            LOG.info("MQTT connected; synchronized authoritative state")
            while not stopped():
                session.pump()
                for _ in range(len(session.messages)):
                    topic, raw, retained = session.messages.popleft()
                    apply_message(engine, session, topic, raw, retained)
                session.publish(engine.tick(now()))
        except (OSError, TransportError) as exc:
            LOG.warning("MQTT unavailable: %s", exc)
        finally:
            session.close()
        until = time.monotonic() + 3
        while not stopped() and time.monotonic() < until:
            engine.tick(now())
            time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    run(Engine(Store(args.state)), args.host, args.port,
        os.environ.get("MQTT_USERNAME"), os.environ.get("MQTT_PASSWORD"), lambda: stopping)


if __name__ == "__main__":
    main()
