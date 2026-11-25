"""DigitalHouses Electrica App: Ingress, persistent bindings and MQTT engine."""
from __future__ import annotations
import logging
import os
import json
from pathlib import Path

from electrica.runtime import Application
from electrica.binding_store import BindingStore
from electrica.supervisor import SupervisorOptions


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
    application = Application(mqtt, version=version, options=BindingStore(SupervisorOptions()))
    application.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
