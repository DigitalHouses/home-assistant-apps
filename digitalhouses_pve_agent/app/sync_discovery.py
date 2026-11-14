"""DH Sync v1 product-source announcement (not an installation authorization)."""
from __future__ import annotations

import json

PRODUCT_ID = "digitalhouses_pve_agent"
REPOSITORY = "https://github.com/DigitalHouses/home-assistant-apps"
PRODUCT_PATH = "digitalhouses_pve_agent"


def build_sync_payload(version: str) -> str:
    """Describe the running release obtained by main._version(), never a YAML commit."""
    return json.dumps(
        {
            "schema": 1,
            "product_id": PRODUCT_ID,
            "type": "agent",
            "version": version,
            "repository": REPOSITORY,
            "product_path": PRODUCT_PATH,
        },
        separators=(",", ":"),
    )
