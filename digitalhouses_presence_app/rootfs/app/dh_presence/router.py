"""Read-only HA router association source for registered resident Wi-Fi status.

The *only* runtime Wi-Fi evidence is one uniquely matched router device_tracker
linked at enrollment. IP, hostname, PING and ARP never determine home/away.
Registration itself continues to use a one-time active ARP MAC verification.
"""
from __future__ import annotations

from datetime import datetime

from dh_presence.core import Engine, Status
from dh_presence.registration import normalized_mac


def poll_router_trackers(
    engine: Engine, registrations: list[dict], states: list[dict],
    observed_at: datetime,
) -> list[dict]:
    """Apply one HA /api/states observation; reject missing/ambiguous evidence.

    A known HA router state of not_home is definitive, including when WLAN
    metadata is omitted on disconnection. Unknown/unavailable/mismatched MAC,
    stale bindings and duplicate source entities are always UNAVAILABLE.
    """
    by_gps = {r["tracker"]: r for r in registrations}
    by_entity = {}
    matched_by_mac = {}
    for item in states:
        if not isinstance(item, dict):
            continue
        entity = item.get("entity_id")
        if not isinstance(entity, str) or not entity.startswith("device_tracker."):
            continue
        by_entity[entity] = item
        attrs = item.get("attributes")
        if (not isinstance(attrs, dict) or attrs.get("source_type") != "router"
                or attrs.get("network_type") == "LAN"):
            continue
        try:
            mac = normalized_mac(attrs.get("mac_address") or attrs.get("mac") or "")
        except ValueError:
            continue
        matched_by_mac.setdefault(mac, set()).add(entity)

    events = []
    for resident in engine.residents.values():
        resident.wifi_source = "router"
        record = by_gps.get(resident.tracker)
        current_link = record.get("wifi_tracker") if record else None
        if current_link != resident.wifi_tracker_id:
            # A registration update may replace the linked router entity.
            # Start from unknown with a fresh baseline, not a fake Wi-Fi out/in.
            resident.wifi_tracker_id = current_link
            if resident.wifi is not Status.UNAVAILABLE:
                resident.wifi_changed_at = observed_at
            resident.wifi = Status.UNAVAILABLE
            resident.wifi_last_decisive = Status.UNAVAILABLE
            resident.wifi_monitor_initialized = False
            resident.wifi_method_baseline_pending = False
            resident.last_wifi_at = None
            resident.initialized = False
        reason = "router_not_registered"
        state = Status.UNAVAILABLE
        if record is not None:
            linked = record.get("wifi_tracker")
            if not linked:
                reason = "router_not_linked"
            elif linked not in by_entity:
                reason = "router_missing"
            else:
                attrs = by_entity[linked].get("attributes")
                attrs = attrs if isinstance(attrs, dict) else {}
                matches = matched_by_mac.get(normalized_mac(record["mac"]), set())
                if len(matches) > 1:
                    reason = "router_ambiguous"
                elif linked not in matches:
                    reason = "router_mac_or_source_mismatch"
                else:
                    raw_state = by_entity[linked].get("state")
                    if raw_state in ("home", "not_home"):
                        state = Status(raw_state)
                        reason = "router_" + raw_state
                    else:
                        reason = "router_unavailable"
        # Treat the first trusted router observation as a baseline even when
        # persistent overall status was restored from an earlier run.
        if state is not Status.UNAVAILABLE and not resident.wifi_monitor_initialized:
            resident.initialized = False
        events.extend(engine.wifi_observation(
            resident.tracker, state, observed_at,
            verified=state is not Status.UNAVAILABLE,
        ))
        resident.wifi_last_probe_at = observed_at
        resident.wifi_probe_result = reason
        # First known observation establishes baseline, not a synthetic event.
        if state is not Status.UNAVAILABLE:
            resident.wifi_monitor_initialized = True
    return events
