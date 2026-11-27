"""DigitalHouses Actions App: Ingress, persistent bindings and MQTT engine."""
from __future__ import annotations
import logging
import os
import json
from pathlib import Path

from actions.runtime import Application
from actions.binding_store import BindingStore
from actions.supervisor import SupervisorOptions


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
    application = Application(mqtt, version=version, options=BindingStore(SupervisorOptions()),
                              event_log_path=Path("/data/actions_log.sqlite3"))
    application.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
