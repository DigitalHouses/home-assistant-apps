"""Conservative native Wi-Fi presence evidence for registered phones.

The only positive Wi-Fi signal in this pilot is a fresh, direct on-link ARP
reply whose source MAC matches the phone's verified enrollment MAC. A missed
reply, wrong MAC, unreachable subnet or probe error is NEVER proof of absence.
Do not add negative presence or `wifi_out` from these observations.

iOS sleep mode may silence ARP while the phone remains on Wi-Fi.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from .core import Engine, Status
from .registration import active_arp_mac, normalized_mac

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
    except (RuntimeError, OSError, ValueError, TimeoutError):
        # `arping` no-reply and host-route problems are UNKNOWN, not away.
        return WifiEvidence(False, "no_verified_reply")
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
        resident.wifi_last_probe_at = observed_at
        resident.wifi_probe_result = evidence.reason
        if evidence.positive:
            events.extend(engine.wifi_observation(
                resident.tracker, Status.HOME, observed_at, verified=True
            ))
            # A real matching MAC updates the last confirmed Wi-Fi contact.
        elif evidence.reason == "mac_mismatch":
            # The saved IP now belongs to a different device; no Wi-Fi HOME
            # evidence should survive this identity conflict.
            resident.wifi = Status.UNAVAILABLE
            resident.wifi_absent_since = None
        # All other no-replies preserve the last positive observation until
        # engine.expire makes it unknown. They NEVER mark NOT_HOME.
        # Baseline first observation separately to avoid notifications from
        # service startup when a phone was already connected to Wi-Fi.
        resident.wifi_monitor_initialized = True
    return events
