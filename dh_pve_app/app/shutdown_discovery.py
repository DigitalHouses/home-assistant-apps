from __future__ import annotations

from collections.abc import Mapping

from .discovery_groups import route_pve_discovery_groups
from .shutdown_discovery_base import build_shutdown_aware_pve_discovery_payload as _base_pve
from .shutdown_discovery_base import build_shutdown_aware_ups_discovery_payload
from .topics import build_topics


def build_shutdown_aware_pve_discovery_payload(
    config,
    identity,
    *,
    version: str,
    inventory: Mapping[str, object] | None = None,
):
    payload = _base_pve(
        config,
        identity,
        version=version,
        inventory=inventory,
    )
    return route_pve_discovery_groups(
        payload,
        build_topics(config.mqtt, identity),
        inventory=inventory or {},
    )
