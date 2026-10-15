"""Native registered-MAC ARP observations: positive, completed negative, unknown.

A completed on-link ARP with zero replies can yield NOT_HOME after a continuous
configured grace period. Infrastructure errors or conflicting MACs are unknown.
iOS can sleep through ARP; this is experimental network reachability, not
cryptographic proof of Wi-Fi disconnection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from .core import Engine, Status
from .registration import ArpNoReply, active_arp_mac, normalized_mac

LOG = logging.getLogger(__name__)
WIFI_PROBE_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class WifiEvidence:
    positive: bool
    reason: str
    interface: str | None = None


def probe_registered_phone(record: dict, arp_probe=active_arp_mac) -> WifiEvidence:
    """Use registered IP+MAC; never discover/guess an unrelated resident."""
    expected = normalized_mac(record["mac"])
    try:
        received, interface = arp_probe(record["ip"])
    except ArpNoReply:
        return WifiEvidence(False, "no_reply")
    except (RuntimeError, OSError, ValueError, TimeoutError):
        return WifiEvidence(False, "probe_error")
    if normalized_mac(received) != expected:
        # IP reassignment or proxying: don't confuse someone else's device.
        return WifiEvidence(False, "mac_mismatch")
    return WifiEvidence(True, "mac_verified", interface)


def poll_registered_wifi(
    engine: Engine, registrations: list[dict], observed_at: datetime,
    probe=probe_registered_phone,
) -> list[dict]:
    """Refresh only enrolled residents without altering GPS or emitting away."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Timezone-aware Wi-Fi observation required")
    linked = {item["tracker"]: item for item in registrations}
    events = []
    for resident in engine.residents.values():
        record = linked.get(resident.tracker)
        if record is None:
            resident.wifi_probe_result = "not_registered"
            resident.wifi_last_probe_at = observed_at
            # A manually configured legacy GPS tracker has no verified MAC.
            resident.wifi = Status.UNAVAILABLE
            continue
        evidence = probe(record)
        if evidence.positive:
            events.extend(engine.wifi_observation(
                resident.tracker, Status.HOME, observed_at, verified=True
            ))
        elif evidence.reason == "no_reply":
            events.extend(engine.wifi_no_reply(resident.tracker, observed_at))
        else:
            # MAC conflict, route problems and command failures are unknown,
            # not proof that the resident left.
            engine.wifi_probe_failed(resident.tracker, observed_at)
        resident.wifi_last_probe_at = observed_at
        resident.wifi_probe_result = evidence.reason
        # First successful positive sample is a baseline, not a synthetic
        # notification. A debounced completed negative is a later transition.
        resident.wifi_monitor_initialized = True
    return events
