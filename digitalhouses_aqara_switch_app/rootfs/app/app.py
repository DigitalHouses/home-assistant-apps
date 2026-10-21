"""DigitalHouses Aqara Switch App — manual-scan pilot runtime.

This version does NOT handle physical button events or write physical relay
states. Only the UI's explicit Scan button imports new confirmed devices.
"""
from __future__ import annotations
import logging
import os
import json
from pathlib import Path

from aqara_switch.runtime import Application


def main() -> int:
    version = os.environ.get("APP_VERSION")
    if not version:
        raise RuntimeError("APP_VERSION must be set")
    raw = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
    level = raw.get("log_level")
    if level not in ("debug", "info", "warning", "error"):
        raise ValueError("Invalid log_level in Supervisor options")
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    import paho.mqtt.client as mqtt
    application = Application(mqtt, version=version)
    application.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
