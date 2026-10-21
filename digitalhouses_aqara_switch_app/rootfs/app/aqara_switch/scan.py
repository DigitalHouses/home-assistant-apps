"""Safe user-requested scan transaction; never called by startup or timers."""
from __future__ import annotations
from datetime import datetime, timezone
from collections.abc import Mapping

from .catalog import CatalogError, candidate_from_mqtt, decode_bridge_devices, import_new
from .configuration import parse_configuration, replace_configuration
from .ha_registry import areas_from_registries


def scan_once(snapshots: list[dict], options_client, ha_registry) -> tuple[dict, dict]:
    """Scan currently observed MQTT snapshots, save new devices to App Options.

    Required bridge info/devices and observed physical MQTT settings must exist.
    Never send MQTT device requests or rewrite known logical switches.
    """
    candidates = []
    problems = []
    ready = 0
    if not snapshots:
        raise CatalogError("No verified Zigbee2MQTT networks observed")
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            raise CatalogError("Invalid Zigbee2MQTT scan snapshot")
        base = snapshot.get("base_topic")
        coordinator = snapshot.get("coordinator_ieee")
        raw = snapshot.get("devices")
        if not isinstance(raw, bytes) or not isinstance(base, str):
            raise CatalogError(f"Zigbee2MQTT inventory incomplete: {base}")
        devices = decode_bridge_devices(raw)
        ready += 1
        states = snapshot.get("states")
        if not isinstance(states, Mapping):
            raise CatalogError("Invalid Zigbee2MQTT reported state snapshot")
        for device in devices:
            try:
                item = candidate_from_mqtt(
                    device, coordinator_ieee=coordinator,
                    base_topic=base,
                    reported_state=states.get(device.get("friendly_name")),
                )
            except (CatalogError, TypeError) as exc:
                name = device.get("friendly_name")
                problems.append({
                    "name": name if isinstance(name, str) else "?",
                    "reason": str(exc),
                })
                continue
            if item is not None:
                candidates.append(item)
    if not ready:
        raise CatalogError("No Zigbee2MQTT inventories are ready")
    # An HA area lookup failure aborts entire transaction, not a fake Unassigned.
    devices, areas = ha_registry.fetch()
    area_index = areas_from_registries(
        devices, areas, {item["ieee"] for item in candidates}
    )
    # Supervisor is read immediately before the merge; scanner never uses stale
    # startup options. Own-App writes are serialized by the runtime operation lock.
    options = options_client.read()
    previous = parse_configuration(options)
    merged, report = import_new(previous, candidates, area_index)
    report["problems"].extend(problems)
    report["networks"] = ready
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    if report["added"]:
        options_client.write(replace_configuration(options, merged))
    return merged, report
