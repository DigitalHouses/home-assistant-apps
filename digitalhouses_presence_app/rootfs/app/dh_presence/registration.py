"""Private mobile enrollment registry owned by the single DH Presence App.

Supervisor Ingress authenticates the user. An on-link active ARP reply provides
the current LAN MAC; stale neighbour cache and browser-supplied IP/MAC are never
accepted as proof. One-time ARP must not become a presence/absence detector.
"""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess

from dh_presence.storage import atomic_json

MAC_RE = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
BAD_INTERFACES = ("lo", "veth", "docker", "br-", "wg", "tun", "tailscale", "zt")

class ArpNoReply(RuntimeError):
    """A valid local active ARP probe completed without a response."""



def normalized_mac(raw: str) -> str:
    mac = str(raw).strip().lower()
    if not MAC_RE.fullmatch(mac):
        raise ValueError("Invalid MAC format")
    first = int(mac.split(":")[0], 16)
    if first & 1 or mac == "00:00:00:00:00:00":
        raise ValueError("Multicast/zero MAC is not a phone address")
    return mac


def validate_entry(entry: dict) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("Registration must be a map")
    required = ("user_id", "user_name", "device_name", "device_id",
                "entry_id", "tracker", "ip", "mac")
    if any(not isinstance(entry.get(key), str) or not entry[key].strip()
           for key in required):
        raise ValueError("Incomplete registration")
    if not entry["tracker"].startswith("device_tracker.") or len(entry["tracker"]) <= 15:
        raise ValueError("Invalid registered tracker")
    ip = ipaddress.ip_address(entry["ip"])
    if not isinstance(ip, ipaddress.IPv4Address) or not ip.is_private or ip.is_loopback or ip.is_link_local:
        raise ValueError("Nonlocal registration IP")
    normalized_mac(entry["mac"])
    clean = {key: entry[key] for key in required}
    wifi_tracker = entry.get("wifi_tracker")
    if wifi_tracker is not None:
        if (not isinstance(wifi_tracker, str)
                or not re.fullmatch(r"device_tracker\\.[a-z0-9_]+", wifi_tracker)):
            raise ValueError("Invalid Wi-Fi device_tracker binding")
        if wifi_tracker == entry["tracker"]:
            raise ValueError("Wi-Fi tracker must differ from GPS tracker")
        clean["wifi_tracker"] = wifi_tracker
    return clean


def load_registry(path: str) -> list[dict]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("residents"), list):
        raise ValueError("Corrupt presence registration state")
    residents = [validate_entry(item) for item in raw["residents"]]
    if len({r["tracker"] for r in residents}) != len(residents):
        raise ValueError("Duplicate registration trackers")
    return residents


def save_registry(path: str, residents: list[dict]) -> None:
    clean = [validate_entry(item) for item in residents]
    if len({r["tracker"] for r in clean}) != len(clean):
        raise ValueError("Duplicate registration trackers")
    atomic_json(path, {"schema_version": 1, "residents": clean})


def put_registration(residents: list[dict], entry: dict) -> list[dict]:
    clean = validate_entry(entry)
    # A single Mobile Companion device cannot silently become two residents.
    for old in residents:
        if old["tracker"] == clean["tracker"]:
            if old["user_id"] != clean["user_id"]:
                raise ValueError("Registered GPS tracker belongs to another HA user")
            if normalized_mac(old["mac"]) != normalized_mac(clean["mac"]):
                raise ValueError("Registered GPS tracker has a different Wi-Fi MAC")
        if old["device_id"] == clean["device_id"] and old["tracker"] != clean["tracker"]:
            raise ValueError("Device already bound to a different tracker")
        if (normalized_mac(old["mac"]) == normalized_mac(clean["mac"])
                and old["tracker"] != clean["tracker"]):
            raise ValueError("Wi-Fi MAC already bound to a different resident")
        if (clean.get("wifi_tracker") and old.get("wifi_tracker") == clean["wifi_tracker"]
                and old["tracker"] != clean["tracker"]):
            raise ValueError("Wi-Fi tracker already bound to a different resident")
    return [*(r for r in residents if r["tracker"] != clean["tracker"]), clean]


def run_checked(argv: list[str], timeout: float = 5) -> str:
    result = subprocess.run(argv, check=False, capture_output=True, text=True,
                            timeout=timeout)
    if result.returncode != 0:
        # iputils arping exits 1 when no response was received. Only an
        # explicit zero-response summary with no stderr is negative evidence;
        # invalid interface, permission, route and subprocess errors are not.
        if (argv and argv[0] == "arping" and result.returncode == 1
                and not result.stderr.strip()
                and re.search(r"(?i)\bReceived\s+0\s+response\(s\)", result.stdout)):
            raise ArpNoReply("Active on-link ARP completed without a reply")
        raise RuntimeError("Probe command failed: " + argv[0])
    return result.stdout


def active_arp_mac(ip_text: str) -> tuple[str, str]:
    """Return (fresh MAC, device interface) only on a directly connected LAN."""
    ip = ipaddress.ip_address(ip_text)
    if (not isinstance(ip, ipaddress.IPv4Address) or not ip.is_private
            or ip.is_loopback or ip.is_link_local):
        raise ValueError("Not a private LAN address")
    route = run_checked(["ip", "-4", "route", "get", ip_text])
    match = re.search(r"\bdev\s+(\S+)", route)
    if not match or re.search(r"\bvia\b", route):
        raise ValueError("Peer is not directly on-link")
    interface = match.group(1)
    if interface.startswith(BAD_INTERFACES):
        raise ValueError("Proxy/VPN/virtual interface is not permitted")
    addresses = json.loads(run_checked(["ip", "-j", "-4", "addr", "show", "dev", interface]))
    connected = any(
        ip in ipaddress.ip_network(f"{item['local']}/{item['prefixlen']}", strict=False)
        for device in addresses for item in device.get("addr_info", [])
        if item.get("family") == "inet"
    )
    if not connected:
        raise ValueError("Peer is not in a directly connected local subnet")
    # Explicit active ARP, not stale 'ip neigh' data. The Host-network App
    # must have CAP_NET_RAW; failure is a hard registration failure.
    output = run_checked(["arping", "-I", interface, "-c", "2", "-w", "3", ip_text], timeout=6)
    pattern = re.compile(r"(?i)\breply\s+from\s+" + re.escape(ip_text)
                         + r"\s+\[([0-9a-f:]{17})\]")
    macs = {normalized_mac(match.group(1)) for match in pattern.finditer(output)}
    if len(macs) != 1:
        raise ValueError("No unique fresh ARP reply from the selected phone IP")
    return macs.pop(), interface


def completed_record(pending: dict, mac: str) -> dict:
    return validate_entry({
        "user_id": pending["user_id"],
        "user_name": pending["user_name"],
        "device_name": pending["device_name"],
        "device_id": pending["device_id"],
        "entry_id": pending["entry_id"],
        "tracker": pending["tracker"],
        "ip": pending["ip"],
        "mac": mac,
    })
