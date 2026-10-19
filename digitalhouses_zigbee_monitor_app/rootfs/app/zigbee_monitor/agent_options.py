"""Optional HA App configuration for automatically discovered Zigbee infrastructure.

Supervisor Options are the sole editable source of truth. Network identity and
Zigbee topology remain authoritative in Zigbee2MQTT MQTT / SQLite. Neither
autofill nor IP checking sends Zigbee commands or enables any Healer action.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any, Mapping

LOG = logging.getLogger(__name__)
_IEEE = re.compile(r"^0x[0-9a-f]{16}$")
_SLUG = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_SWITCH = re.compile(r"^switch\.[a-z0-9_]+$")
_REPEATER_MODELS = frozenset({
    # Explicitly model-identified dedicated repeaters, NOT every Router.
    "ZigStar-01", "ZigStar-01 Repeater",
})
_MAX_COORDINATORS = 64
_MAX_REPEATERS = 256
_METHODS = ("disabled", "addon_restart", "power_cycle")
_KEYS = ("ieee", "name", "model", "critical", "management_ip",
         "addon_slug", "healer_method", "power_switch")


def normalize_ieee(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    ieee = value.strip().lower()
    return ieee if _IEEE.fullmatch(ieee) else None


def management_address(value: object) -> str | None:
    """Pure IP only. A missing/invalid address never blocks App startup."""
    if not isinstance(value, str) or not value:
        return None
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    if ip.is_multicast or ip.is_unspecified or ip.is_loopback:
        return None
    return str(ip)


def _clean_entry(raw: object, *, repeater: bool = False) -> dict[str, object] | None:
    if not isinstance(raw, Mapping):
        return None
    ieee = normalize_ieee(raw.get("ieee"))
    if ieee is None:
        return None
    entry: dict[str, object] = {"ieee": ieee}
    fields = ("name", "model", "management_ip", "power_switch") if repeater else (
        "name", "model", "management_ip", "addon_slug", "power_switch"
    )
    for field in fields:
        value = raw.get(field, "")
        if not isinstance(value, str) or len(value) > 253 or any(
            ord(c) < 32 or ord(c) == 127 for c in value
        ):
            continue
        if field in ("name", "model") and len(value) > 64:
            continue
        if field == "addon_slug" and value and not _SLUG.fullmatch(value):
            continue
        if field == "power_switch" and value and not _SWITCH.fullmatch(value):
            continue
        entry[field] = value
    entry["critical"] = raw.get("critical") if type(raw.get("critical")) is bool else False
    if not repeater:
        method = raw.get("healer_method")
        entry["healer_method"] = method if method in _METHODS else "disabled"
    return entry


def normalize_registry(raw: Mapping[str, Any] | object) -> dict[str, list[dict[str, object]]]:
    """Ignore bad/incomplete optional entries; never prevent service startup."""
    src = raw if isinstance(raw, Mapping) else {}
    result: dict[str, list[dict[str, object]]] = {}
    seen: set[str] = set()
    for key, limit in (("coordinators", _MAX_COORDINATORS),
                       ("repeaters", _MAX_REPEATERS)):
        arr = src.get(key, [])
        entries = []
        if isinstance(arr, list):
            for obj in arr[:limit]:
                parsed = _clean_entry(obj, repeater=(key == "repeaters"))
                if parsed is None or parsed["ieee"] in seen:
                    continue
                seen.add(str(parsed["ieee"]))
                entries.append(parsed)
        result[key] = entries
    return result


def is_recognized_repeater(device: object) -> bool:
    # Device must be an actual Zigbee Router. "Router" alone is NOT a repeater.
    return (
        getattr(device, "device_type", None) == "Router"
        and getattr(device, "model", None) in _REPEATER_MODELS
    )


def merge_new_discoveries(
    options: Mapping[str, Any],
    coordinator_candidates: list[dict[str, object]],
    repeater_candidates: list[dict[str, object]],
    legacy: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Append only confirmed new IEEE; preserve every existing user entry.

    The HA Supervisor config is read immediately before writing, to avoid
    overwriting user edits. This function is pure and idempotent.
    """
    merged = dict(options)
    changed = False
    known = normalize_registry(options)
    occupied = {str(row["ieee"]) for group in known.values() for row in group}
    for key, candidates, limit in (
        ("coordinators", coordinator_candidates, _MAX_COORDINATORS),
        ("repeaters", repeater_candidates, _MAX_REPEATERS),
    ):
        original = options.get(key)
        if original is not None and not isinstance(original, list):
            # Unknown shape => no destructive rewrite.
            continue
        rows = list(original or [])
        for candidate in candidates:
            ieee = normalize_ieee(candidate.get("ieee"))
            if not ieee or ieee in occupied or len(rows) >= limit:
                continue
            if key == "repeaters" and not candidate.get("recognized", False):
                continue
            fresh: dict[str, object] = {
                "ieee": ieee,
                "name": str(candidate.get("name") or "")[:64],
                "model": str(candidate.get("model") or "")[:64],
                "critical": False,
                "management_ip": (
                    str(candidate.get("management_ip"))
                    if management_address(candidate.get("management_ip")) else ""
                ),
                "power_switch": "",
            }
            if key == "coordinators":
                fresh.update({"addon_slug": "", "healer_method": "disabled"})
                previous = (legacy or {}).get(str(candidate.get("network_id")), {})
                if previous:
                    for key_old, key_new in (
                        ("display_name", "name"), ("hardware_model", "model"),
                        ("management_host", "management_ip"), ("addon_slug", "addon_slug"),
                        ("power_switch", "power_switch"), ("critical", "critical"),
                        ("healer_method", "healer_method"),
                    ):
                        item = previous.get(key_old)
                        if key_new == "management_ip" and management_address(item) is None:
                            continue
                        if item not in ("", None, False):
                            fresh[key_new] = item
            rows.append(fresh)
            occupied.add(ieee)
            changed = True
        if changed and rows != original:
            merged[key] = rows
    return merged, changed


class SupervisorOptions:
    """Unprivileged own-App GET and POST; never operates on another App."""
    def __init__(self, token: str | None = None, *,
                 base_url: str = "http://supervisor", timeout: float = 5.0):
        self.token = token if token is not None else os.getenv("SUPERVISOR_TOKEN", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("Supervisor token is unavailable")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data,
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as res:
            body = res.read(524289)
        if len(body) > 524288:
            raise ValueError("Supervisor response exceeds size limit")
        response = json.loads(body)
        if not isinstance(response, dict) or response.get("result") != "ok":
            raise ValueError("Supervisor rejected own App Options request")
        return response

    def read(self) -> dict[str, Any]:
        obj = self._request("/addons/self/options/config").get("data")
        if not isinstance(obj, dict):
            raise ValueError("invalid own App Options response")
        return obj

    def write(self, options: Mapping[str, Any]) -> None:
        # Fail closed: never modify the Supervisor settings unless the
        # Supervisor itself confirms the candidate fits the live schema.
        checked = self._request("/addons/self/options/validate", dict(options))
        detail = checked.get("data")
        if not isinstance(detail, dict) or detail.get("valid") is not True:
            raise ValueError("Supervisor rejected discovered Zigbee configuration")
        self._request("/addons/self/options", {"options": dict(options)})


def ping_management_ip(value: object, *, timeout: int = 2) -> str:
    """One bounded ICMP probe. Failure is QUESTION, not Zigbee-down proof."""
    ip = management_address(value)
    if ip is None:
        return "not_configured" if not value else "invalid"
    if timeout not in (1, 2, 3):
        raise ValueError("unsupported ping timeout")
    try:
        proc = subprocess.run(
            ["ping", "-n", "-c", "1", "-W", str(timeout), ip],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=timeout + 2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if proc.returncode == 0:
        return "reachable"
    error = proc.stderr.decode("utf-8", errors="replace").lower()[:1024]
    if "permission" in error or "operation not permitted" in error:
        return "unknown"
    return "no_response"
