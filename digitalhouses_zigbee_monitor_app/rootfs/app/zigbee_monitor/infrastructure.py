"""Safe passive projection of Zigbee2MQTT bridge/info for infrastructure tree."""
from __future__ import annotations
import ipaddress
import json
import re
from urllib.parse import urlsplit
from .core import ZigbeeMonitorError

_IEEE = re.compile(r"^0x[0-9a-f]{16}$")
_SAFE = re.compile(r"^[a-zA-Z0-9_.+-]{1,64}$")
_HOST = re.compile(r"^[a-zA-Z0-9_.-]{1,253}$")

def _string(value: object, maxlen: int = 64) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= maxlen and _SAFE.fullmatch(value) else None

def _number(value: object, low: int, high: int) -> int | None:
    return value if type(value) is int and low <= value <= high else None

def _serial(port: object) -> tuple[str, str | None, str | None, str | None]:
    """No credentials, query strings, paths or arbitrary ports stored."""
    if not isinstance(port, str) or len(port) > 256:
        return "unknown", None, None, None
    if port.startswith("/dev/") and re.fullmatch(r"/dev/[a-zA-Z0-9_/.-]+", port):
        if ".." not in port.split("/"):
            return "usb", port, None, None
    if port.startswith(("tcp://", "socket://")):
        try:
            uri = urlsplit(port)
            if (uri.username or uri.password or uri.path or uri.query or uri.fragment
                    or not uri.hostname or uri.port is None
                    or not 1 <= uri.port <= 65535):
                return "unknown", None, None, None
            host = uri.hostname
            try:
                ip = str(ipaddress.ip_address(host))
            except ValueError:
                ip = None
                if not _HOST.fullmatch(host):
                    return "unknown", None, None, None
            safe_host = f"[{host}]" if ":" in host else host
            return "tcp", f"{uri.scheme}://{safe_host}:{uri.port}", host, ip
        except (ValueError, AttributeError):
            return "unknown", None, None, None
    return "unknown", None, None, None

def parse_bridge_infrastructure(payload: bytes, *, expected_ieee: str | None = None) -> dict[str, object]:
    """Only fixed allowlisted metadata; never interpret it as a coordinator health probe."""
    if not isinstance(payload, bytes) or len(payload) > 2_000_000:
        raise ZigbeeMonitorError("bridge/info payload too large")
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ZigbeeMonitorError("invalid bridge/info JSON") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("coordinator"), dict):
        raise ZigbeeMonitorError("bridge/info coordinator required")
    coord = raw["coordinator"]
    ieee = coord.get("ieee_address")
    if not isinstance(ieee, str) or not _IEEE.fullmatch(ieee.lower()):
        raise ZigbeeMonitorError("bridge/info coordinator IEEE invalid")
    ieee = ieee.lower()
    if expected_ieee is not None and ieee != expected_ieee:
        raise ZigbeeMonitorError("bridge/info coordinator identity mismatch")
    config = raw.get("config") if isinstance(raw.get("config"), dict) else {}
    serial = config.get("serial") if isinstance(config.get("serial"), dict) else {}
    network = raw.get("network") if isinstance(raw.get("network"), dict) else {}
    meta = coord.get("meta") if isinstance(coord.get("meta"), dict) else {}
    transport, port, host, ip = _serial(serial.get("port"))
    return {
        "coordinator_ieee": ieee,
        "coordinator_type": _string(coord.get("type")),
        "firmware_revision": _number(meta.get("revision"), 0, 2**63-1),
        "z2m_version": _string(raw.get("version"), 64),
        "connection": transport,
        "serial_port": port,
        "serial_adapter": _string(serial.get("adapter")),
        "network_host": host,
        "ip": ip,
        "channel": _number(network.get("channel"), 11, 26),
        "pan_id": _number(network.get("pan_id"), 0, 65535),
        "restart_required": raw.get("restart_required")
        if type(raw.get("restart_required")) is bool else None,
    }
