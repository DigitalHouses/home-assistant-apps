"""DigitalHouses Internet App — DH Sync Discovery Contract v1.

This source announcement is independent of the historical Internet App MQTT
telemetry namespace. No device, entity, availability or runtime topic changes.
"""

from __future__ import annotations

import json

SYNC_TOPIC = "DigitalHouses/Global/digitalhouses_internet_app/sync"
PRODUCT_ID = "digitalhouses_internet_app"
REPOSITORY = "https://github.com/DigitalHouses/home-assistant-apps"
PRODUCT_PATH = "digitalhouses_internet_app"
DASHBOARD = "dh-system"


def build_sync_payload(version: str) -> str:
    """Announce running release on every successful MQTT connect/reconnect."""
    return json.dumps(
        {
            "schema": 1,
            "product_id": PRODUCT_ID,
            "type": "app",
            "version": version,
            "repository": REPOSITORY,
            "product_path": PRODUCT_PATH,
            "dashboard": DASHBOARD,
        },
        separators=(",", ":"),
    )
