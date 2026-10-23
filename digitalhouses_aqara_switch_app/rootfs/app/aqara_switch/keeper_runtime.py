"""Runtime state machine for Aqara key Mode Keeper.

MQTT-driven with a debounce timer. Never act based solely on retained Z2M
state, treat /set acceptance as unconfirmed, and only restore a declared key.
"""
from __future__ import annotations
from collections.abc import Mapping
import json
import logging
import time
from .catalog import CatalogError, _exposes, decode_bridge_devices
from .control import verified_adopted_switch
from .mode_keeper import capabilities, maintained_switch, next_repair

LOG = logging.getLogger(__name__)
RETRY_SECONDS = 60
PROBE_SECONDS = 30


def tick(app, now: float) -> None:
    """Run under app._mutex, with strictly verified observed hardware."""
    for room in app.config["rooms"]:
        for sw in room["switches"]:
            if not sw.get("enabled", False) or not sw.get("keep_mode"):
                continue
            base, name = sw["base_topic"], sw["logical_name"]
            net = app._networks.get(base, {})
            if not isinstance(net.get("devices"), bytes) or not isinstance(net.get("info"), bytes):
                continue
            try:
                coordinator = json.loads(net["info"])["coordinator"]["ieee_address"].lower()
                if coordinator != sw["coordinator_ieee"]:
                    continue
                devices = decode_bridge_devices(net["devices"])
                device = next((d for d in devices
                               if d.get("friendly_name") == name), None)
                if device is None or not verified_adopted_switch(sw, device, coordinator, base):
                    continue
                features = capabilities(device)
                if set(sw["keep_mode"]) - set(features):
                    continue
                state = net.get("states", {}).get(name, {})
                if not isinstance(state, Mapping):
                    continue
                maintenance = maintained_switch(sw, app.globals)
                # Force a fresh observation after each MQTT reconnect before
                # any physical /set. Retained state may be stale.
                needed = {}
                for key in sw["keep_mode"]:
                    mode, relay = features[key]
                    for field in ((mode,) if maintenance else (mode, relay)):
                        if (base, name, field) not in app._fresh_fields:
                            needed[field] = ""
                if needed:
                    last = app._mode_probes.get((base, name), -1e9)
                    if now - last >= PROBE_SECONDS:
                        exposed = {f.get("property", f.get("name")): f
                                   for f in _exposes(device["definition"].get("exposes", []))}
                        get_payload = {
                            prop: "" for prop in needed
                            if (isinstance(exposed.get(prop), Mapping)
                                and type(exposed[prop].get("access")) is int
                                and exposed[prop]["access"] & 4)
                        }
                        if get_payload:
                            app._publish(base + "/" + name + "/get",
                                         get_payload, retain=False)
                            app._mode_probes[(base, name)] = now
                    continue
                wanted = next_repair(sw["keep_mode"], features, state, maintenance)
                if wanted is None:
                    for ident in list(app._mode_pending):
                        if ident[:2] == (base, name):
                            app._mode_pending.pop(ident, None)
                    continue
                field, value = wanted
                ident = (base, name, field, value)
                for old in list(app._mode_pending):
                    if old[:2] == (base, name) and old != ident:
                        app._mode_pending.pop(old, None)
                first = app._mode_pending.setdefault(ident, now)
                last = app._last_mode_request.get(ident, -1e9)
                if (now - first >= app.globals["restore_delay"]
                        and now - last >= RETRY_SECONDS):
                    app._last_mode_request[ident] = now
                    app._publish(base + "/" + name + "/set",
                                 {field: value}, retain=False)
                    LOG.warning("Aqara %s: requested %s=%s (maintenance=%s); "
                                "waiting for actual Z2M report", name, field, value,
                                maintenance)
            except (CatalogError, ValueError, TypeError, KeyError) as exc:
                LOG.warning("Aqara Mode Keeper skipped %s: %s", name, exc)


def run_keeper(app) -> None:
    while not app._stop.wait(0.1):
        with app._mutex:
            tick(app, time.monotonic())
