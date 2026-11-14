"""DH Sync Discovery v1: static product-source announcement.

This payload is an identity claim, not authorization to install YAML or code.
Keep the existing MQTT availability and HA Discovery namespaces unchanged.
"""
from __future__ import annotations

from contracts import validate_release_version
from discovery import BASE_TOPIC, PRODUCT_ID

SYNC_TOPIC = f"{BASE_TOPIC}/sync"
REPOSITORY_URL = "https://github.com/DigitalHouses/home-assistant-apps"
PRODUCT_PATH = PRODUCT_ID


def build_sync_payload(version: str) -> dict[str, int | str]:
    """Build exactly the six contract fields for the running App release."""
    return {
        "schema": 1,
        "product_id": PRODUCT_ID,
        "type": "app",
        "version": validate_release_version(version),
        "repository": REPOSITORY_URL,
        "product_path": PRODUCT_PATH,
    }
