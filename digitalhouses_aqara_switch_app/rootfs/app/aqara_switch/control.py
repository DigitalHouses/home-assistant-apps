"""Narrow first-MVP controller: validated Aqara action -> one HA light.toggle.

Mode Keeper restores *captured configuration keys* only, never physical
relay ON/OFF. No Zigbee control occurs without verified adopted identity.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import logging
import re
import urllib.request

from .actions import ActionError, plan_action
from .catalog import CatalogError, candidate_from_mqtt
from .light_rules import validate_data

LOG = logging.getLogger(__name__)


def verified_adopted_switch(saved: Mapping, device: Mapping,
                            coordinator_ieee: str, base_topic: str) -> bool:
    """Gate actions/restoration on coordinator, physical IEEE and capability profile."""
    if (saved.get("coordinator_ieee") != coordinator_ieee or
            saved.get("base_topic") != base_topic or
            saved.get("logical_name") != device.get("friendly_name") or
            saved.get("ieee") != device.get("ieee_address")):
        return False
    try:
        candidate = candidate_from_mqtt(
            device, coordinator_ieee=coordinator_ieee, base_topic=base_topic,
            reported_state=saved.get("settings"),
        )
        return candidate is not None and candidate["fingerprint"] == saved["fingerprint"]
    except (CatalogError, KeyError, TypeError, ValueError):
        return False


def light_action(saved: Mapping, reported_action: object) -> dict | None:
    """Allow only light.toggle, light.turn_on and light.turn_off with validated data."""
    if not isinstance(reported_action, str) or not reported_action:
        return None
    call = plan_action(saved, reported_action)
    if call is None:
        return None
    if (call.get("service") not in ("light.toggle", "light.turn_on", "light.turn_off") or
            not isinstance(call.get("target"), Mapping) or
            not 1 <= len(call["target"].get("entity_id", [])) <= 16 or
            any(not light.startswith("light.")
                for light in call["target"]["entity_id"])):
        raise ActionError("MVP permits only 1..16 light.* targets per supported light service")
    try:
        validate_data(call["service"], call.get("data", {}))
    except CatalogError as exc:
        raise ActionError(str(exc)) from exc
    return call


def light_commands(saved: Mapping, reported_action: object) -> list[dict] | None:
    """Plan every light command before dispatch; coalesce only equal parameters.

    A multi-light action may need separate calls for lights with distinct
    brightness/color settings. One MQTT press becomes one queued batch.
    """
    base = light_action(saved, reported_action)
    if base is None:
        return None
    binding = saved.get("bindings", {}).get(reported_action, {})
    overrides = binding.get("target_data", {})
    if not isinstance(overrides, Mapping):
        raise ActionError("Invalid per-light options map")
    ids = base["target"]["entity_id"]
    if set(overrides) - set(ids):
        raise ActionError("Per-light options reference unbound target")
    shared = base.get("data", {})
    if shared and overrides:
        raise ActionError("Cannot mix shared and per-light attributes")
    groups: dict[str, dict] = {}
    for entity in ids:
        try:
            data = validate_data(base["service"], overrides.get(entity, shared))
        except CatalogError as exc:
            raise ActionError(str(exc)) from exc
        # Same service and identical parameters can be sent as ONE HA call.
        key = json.dumps(data, ensure_ascii=True, sort_keys=True)
        if key not in groups:
            groups[key] = {
                "service": base["service"], "target": {"entity_id": []},
            }
            if data:
                groups[key]["data"] = data
        groups[key]["target"]["entity_id"].append(entity)
    return list(groups.values())


def settings_drift(saved: Mapping, observed: Mapping) -> dict:
    """Return explicitly observed differing settings from the adopted baseline.

    These keys were enumerated as writable by Z2M at adopt, not live relay state.
    Missing keys do not cause a write; device states may be partial.
    """
    settings = saved.get("settings")
    fingerprint = saved.get("fingerprint")
    if not isinstance(settings, Mapping) or not isinstance(fingerprint, Mapping):
        return {}
    allowed = set(fingerprint.get("setting_keys") or ())
    return {key: baseline for key, baseline in settings.items()
            if key in allowed and key in observed and observed[key] != baseline
            and not key.startswith("state")}


class HAClient:
    """Home Assistant action via Supervisor Core REST proxy."""
    def __init__(self, token: str, *, url: str = "http://supervisor/core/api",
                 timeout: float = 8.0):
        if not token:
            raise ValueError("SUPERVISOR_TOKEN missing")
        self.token = token
        self.url = url.rstrip("/")
        self.timeout = timeout

    def read_lab_state(self, entity_id: str) -> str:
        """Read the state of ONLY an explicitly named virtual AQARA LAB lamp.

        Never use this as fallback for an unmapped or offline physical light.
        """
        from .lab_lights import LAB_LIGHTS
        if entity_id not in LAB_LIGHTS:
            raise ValueError("Reading physical lights via HA fallback is prohibited")
        req = urllib.request.Request(
            self.url + "/states/" + entity_id,
            method="GET", headers={"Authorization": "Bearer " + self.token,
                                   "Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            if response.status != 200:
                raise RuntimeError("HA LAB state query failed")
            data = json.loads(response.read())
        state = data.get("state") if isinstance(data, Mapping) else None
        return state if state in ("on", "off") else "unavailable"

    def toggle(self, entity_id: str) -> None:
        self.toggle_targets([entity_id])

    def toggle_targets(self, entity_ids: list[str]) -> None:
        self.execute({"service": "light.toggle", "target": {"entity_id": entity_ids}})

    def execute(self, command: Mapping) -> None:
        """Call one allowlisted HA light service with validated light data."""
        if not isinstance(command, Mapping):
            raise ValueError("HA light command must be an object")
        service = command.get("service")
        if service not in ("light.toggle", "light.turn_on", "light.turn_off"):
            raise ValueError("Only HA light.toggle/turn_on/turn_off permitted")
        target = command.get("target")
        ids = target.get("entity_id") if isinstance(target, Mapping) else None
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 16 or
                any(not isinstance(e, str) or
                    not re.fullmatch(r"light\.[a-z0-9_]+", e) for e in ids) or
                len(ids) != len(set(ids))):
            raise ValueError("Only 1..16 unique light.* targets are permitted")
        try:
            data = validate_data(service, command.get("data", {}))
        except CatalogError as exc:
            raise ValueError(str(exc)) from exc
        payload = json.dumps({"entity_id": ids, **data}).encode("utf-8")
        endpoint = {"light.toggle": "/services/light/toggle",
                    "light.turn_on": "/services/light/turn_on",
                    "light.turn_off": "/services/light/turn_off"}[service]
        req = urllib.request.Request(
            self.url + endpoint, method="POST", data=payload,
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            if response.status != 200:
                raise RuntimeError("Home Assistant light command was not accepted")

