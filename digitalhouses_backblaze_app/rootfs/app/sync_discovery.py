"""Canonical DH Sync 0.6.0 product-source announcement.

This announcement is separate from the existing Backblaze MQTT Discovery and
data topics. It contains no credentials, bucket names or installation details.
"""
from __future__ import annotations

import json

SYNC_TOPIC = "DigitalHouses/Global/digitalhouses_backblaze_app/sync"
PRODUCT_ID = "digitalhouses_backblaze_app"
REPOSITORY = "https://github.com/DigitalHouses/home-assistant-apps"
PRODUCT_PATH = "digitalhouses_backblaze_app"


def build_sync_payload(version: str) -> str:
    """Return only the six source-identification fields for the running App."""
    return json.dumps(
        {
            "schema": 1,
            "product_id": PRODUCT_ID,
            "type": "app",
            "version": version,
            "repository": REPOSITORY,
            "product_path": PRODUCT_PATH,
        },
        separators=(",", ":"),
    )
