#!/usr/bin/env python3
"""Passive Zigbee2MQTT observer for one real room. No MQTT publishing."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import ssl
import sys
import threading
import time
from urllib.request import Request, urlopen


def ts():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def mqtt_service():
    token = os.getenv("SUPERVISOR_TOKEN") or os.getenv("HASSIO_TOKEN")
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN not available")
    req = Request("http://supervisor/services/mqtt",
                  headers={"Authorization": "Bearer " + token})
    with urlopen(req, timeout=10) as response:
        raw = json.load(response)
    info = raw.get("data", raw)
    if not isinstance(info, dict) or not info.get("host") or not info.get("port"):
        raise RuntimeError("Supervisor MQTT service unavailable to this App")
    return info


def topics(base, group, members):
    result = {base + "/bridge/groups": "membership"}
    for role, name in [("group", group)] + [("member", x) for x in members]:
        topic = base + "/" + name
        result[topic] = role
        result[topic + "/set"] = "command_to_" + role
        result[topic + "/get"] = "read_request_to_" + role
    return result


def compact(payload, role, group):
    try:
        decoded = json.loads(payload)
    except (ValueError, UnicodeError):
        return {"invalid_json": True}
    if role == "membership":
        if not isinstance(decoded, list):
            return {"group_found": False}
        g = next((x for x in decoded if isinstance(x, dict)
                  and x.get("friendly_name") == group), None)
        if not g:
            return {"group_found": False}
        members = g.get("members") or []
        return {"group_found": True, "id": g.get("id"),
                "members": [{"ieee": x.get("ieee_address"), "endpoint": x.get("endpoint")}
                            for x in members if isinstance(x, dict)]}
    if not isinstance(decoded, dict):
        return {"non_object": True}
    allowed = ("state", "brightness", "linkquality", "last_seen", "transition",
               "color_mode", "color_temp", "effect")
    return {key: decoded[key] for key in allowed if key in decoded}


class Observer:
    def __init__(self, mqtt, service, base, group, members, logpath, hours):
        self.service, self.base, self.group = service, base, group
        self.members, self.logpath, self.hours = members, logpath, hours
        self.filters = topics(base, group, members)
        self.stopped = threading.Event()
        self.connected = threading.Event()
        self.lock = threading.RLock()
        self.count = 0
        self.output = None
        if hasattr(mqtt, "CallbackAPIVersion"):
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1,
                                      client_id="dh-aqara-one-room-observer")
        else:
            self.client = mqtt.Client(client_id="dh-aqara-one-room-observer")
        if service.get("username"):
            self.client.username_pw_set(service["username"], service.get("password", ""))
        if service.get("ssl"):
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    def record(self, event, **data):
        line = json.dumps({"ts": ts(), "event": event, **data},
                          ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            if self.output:
                self.output.write(line + "\n")
                self.output.flush()
        print(line, flush=True)

    def on_connect(self, client, userdata, flags, rc):
        if rc:
            self.record("MQTT_CONNECT_ERROR", code=rc)
            return
        for topic in self.filters:
            client.subscribe(topic, qos=0)
        self.connected.set()
        self.record("CONNECTED", topics=len(self.filters))

    def on_disconnect(self, client, userdata, rc):
        if rc:
            self.record("DISCONNECTED", code=rc)

    def on_message(self, client, userdata, message):
        role = self.filters.get(message.topic)
        if role is None:
            return
        if self.count >= 20000:
            self.stopped.set()
            return
        self.count += 1
        self.record("OBSERVED_UNVERIFIED", role=role, topic=message.topic,
                    retained=bool(message.retain),
                    **compact(bytes(message.payload), role, self.group))
        if self.count >= 20000:
            self.record("EVENT_LIMIT_REACHED", max_events=20000)
            self.stopped.set()

    def stop(self, *args):
        self.stopped.set()

    def run(self):
        self.logpath.parent.mkdir(parents=True, exist_ok=True)
        with self.logpath.open("x", encoding="utf-8", buffering=1) as output:
            self.output = output
            self.record("START", group=self.group, members=self.members,
                        hours=self.hours, safety="subscribe-only; no MQTT publish/GET")
            self.client.connect(self.service["host"], int(self.service["port"]), keepalive=60)
            self.client.loop_start()
            start = time.monotonic()
            try:
                if not self.connected.wait(timeout=12):
                    self.record("MQTT_NO_CONNECTION")
                    return 2
                while not self.stopped.wait(timeout=1):
                    if time.monotonic() - start >= self.hours * 3600:
                        break
                self.record("FINISHED", messages=self.count)
                return 0
            finally:
                self.client.disconnect()
                self.client.loop_stop()
                self.output = None


def main(argv=None):
    p = argparse.ArgumentParser(description="Passive one-room Zigbee2MQTT logger")
    p.add_argument("--base", default="zigbee2mqtt_1")
    p.add_argument("--group", default="zg_bedroom_tube_lights")
    p.add_argument("--member", action="append")
    p.add_argument("--hours", type=float, default=18)
    args = p.parse_args(argv)
    try:
        import paho.mqtt.client as mqtt
        members = args.member or ["1f_bedroom_tubelight_L", "1f_bedroom_tubelight_R"]
        values = [args.base, args.group] + members
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", v) for v in values):
            raise ValueError("Invalid MQTT topic segment")
        if not (0.01 <= args.hours <= 48 and 1 <= len(members) <= 20):
            raise ValueError("Invalid observation duration or member count")
        if args.group in members or len(set(members)) != len(members):
            raise ValueError("Duplicate group/member")
        service = mqtt_service()
        folder = Path("/config/dh_aqara_observer")
        file = ("group_" + args.group + "_" +
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".jsonl")
        observer = Observer(mqtt, service, args.base, args.group, members,
                            folder / file, args.hours)
        signal.signal(signal.SIGINT, observer.stop)
        signal.signal(signal.SIGTERM, observer.stop)
        print("LOG_FILE=" + str(observer.logpath), flush=True)
        return observer.run()
    except Exception as exc:
        print("OBSERVER_ERROR=" + str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
