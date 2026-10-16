"""Native registered-MAC ARP observations: positive, completed negative, unknown.

A completed on-link ARP with zero replies can yield NOT_HOME after a continuous
configured grace period. Infrastructure errors or conflicting MACs are unknown.
iOS can sleep through ARP; this is experimental network reachability, not
cryptographic proof of Wi-Fi disconnection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import logging
import re
import subprocess

from .core import Engine, Status
from .registration import ArpNoReply, active_arp_mac, normalized_mac

LOG = logging.getLogger(__name__)
WIFI_PROBE_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class WifiEvidence:
    positive: bool
    reason: str
    interface: str | None = None


def active_ping_ip(ip_text: str, runner=subprocess.run) -> bool:
    """One fresh ICMP probe to a registered private IPv4 address.

    Success authenticates IP reachability, not phone identity. A missing ICMP
    response is meaningful only when ping completes and reports packet loss.
    All command/route/permission failures are UNKNOWN, not absence.
    """
    ip = ipaddress.ip_address(ip_text)
    if not isinstance(ip, ipaddress.IPv4Address) or not ip.is_private or ip.is_loopback or ip.is_link_local:
        raise ValueError("PING requires a registered private LAN IPv4 address")
    result = runner(["ping", "-n", "-c", "1", "-W", "2", ip_text],
                    capture_output=True, text=True, timeout=4, check=False)
    output = result.stdout or ""
    success = re.search(r"\b[1-9]\d*\s+(?:packets\s+)?received\b", output)
    no_reply = re.search(r"\b0\s+(?:packets\s+)?received\b", output)
    if result.returncode == 0 and success:
        return True
    # ICMP failures from a router/interface may still print "0 received".
    # Reject them as unknown instead of treating network failure as absence.
    network_error = re.search(
        r"(?i)(destination\s+(?:host|net|network)\s+unreachable|network\s+is\s+unreachable|"
        r"\b[1-9]\d*\s+errors?\b|time\s+exceeded|sendmsg:|operation\s+not\s+permitted)",
        output,
    )
    if result.returncode == 1 and no_reply and not result.stderr.strip() and not network_error:
        return False
    raise RuntimeError("ICMP probe failed or returned ambiguous output")


def probe_registered_phone(
    record: dict, arp_probe=active_arp_mac, *,
    ping_probe=active_ping_ip, use_ping: bool = False, use_arp: bool = True,
) -> WifiEvidence:
    """Combine enabled methods: any positive means HOME, all verified misses mean no_reply.

    An explicit ARP MAC mismatch takes precedence over an ICMP response:
    address reassignment must never be mistaken for the enrolled phone.
    PING-only relies on a stable private IP/DHCP reservation, not MAC identity.
    """
    if not use_ping and not use_arp:
        return WifiEvidence(False, "disabled")

    arp_positive = False
    arp_negative = False
    arp_interface = None
    arp_error = None
    if use_arp:
        expected = normalized_mac(record["mac"])
        try:
            received, arp_interface = arp_probe(record["ip"])
            if normalized_mac(received) != expected:
                return WifiEvidence(False, "mac_mismatch")
            arp_positive = True
        except ArpNoReply:
            arp_negative = True
        except (RuntimeError, OSError, ValueError, TimeoutError):
            arp_error = "probe_error"

    ping_positive = False
    ping_negative = False
    ping_error = None
    if use_ping:
        try:
            ping_positive = ping_probe(record["ip"]) is True
            ping_negative = not ping_positive
        except (RuntimeError, OSError, ValueError, TimeoutError, subprocess.SubprocessError):
            ping_error = "ping_error"

    if arp_positive and ping_positive:
        return WifiEvidence(True, "mac_and_ping_verified", arp_interface)
    if arp_positive:
        return WifiEvidence(True, "mac_verified", arp_interface)
    if ping_positive:
        return WifiEvidence(True, "ping_reply")
    if arp_error or ping_error:
        return WifiEvidence(False, arp_error or ping_error)
    if (not use_arp or arp_negative) and (not use_ping or ping_negative):
        return WifiEvidence(False, "no_reply")
    return WifiEvidence(False, "probe_error")


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
        # First sample after a method change is a baseline; neither a live
        # MQTT toggle nor a restart may synthesize arrival or departure.
        if evidence.reason != "disabled":
            resident.wifi_monitor_initialized = True
    return events
