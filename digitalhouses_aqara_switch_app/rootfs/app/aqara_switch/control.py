"""Narrow first-MVP controller: validated Aqara action -> one HA light.toggle.

Mode Keeper restores *captured configuration keys* only, never physical
relay ON/OFF. No Zigbee control occurs without verified adopted identity.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import logging
import urllib.request

from .actions import ActionError, plan_action
from .catalog import CatalogError, candidate_from_mqtt

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
    """Configured single light only; older broader planners are not exposed."""
    if not isinstance(reported_action, str) or not reported_action:
        return None
    call = plan_action(saved, reported_action)
    if call is None:
        return None
    if (call.get("service") != "light.toggle" or
            not isinstance(call.get("target"), Mapping) or
            len(call["target"].get("entity_id", [])) != 1 or
            not call["target"]["entity_id"][0].startswith("light.")):
        raise ActionError("MVP permits exactly one light.toggle target per action")
    return call


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

    def toggle(self, entity_id: str) -> None:
        if not isinstance(entity_id, str) or not entity_id.startswith("light."):
            raise ValueError("Only Home Assistant light entities can be toggled")
        payload = json.dumps({"entity_id": entity_id}).encode("utf-8")
        req = urllib.request.Request(
            self.url + "/services/light/toggle", method="POST",
            data=payload,
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            if response.status != 200:
                raise RuntimeError("Home Assistant toggle was not accepted")
