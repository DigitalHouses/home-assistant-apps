"""Publish a single MQTT notification for each newly observed country.

The state file is initialized from existing telemetry on the first run, so
enabling notifications never replays historical countries. A failed MQTT
publish leaves the new country pending for the next scheduled run.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import paho.mqtt.client as mqtt
from sqlalchemy import text

from .db import engine

LOG = logging.getLogger("digitalhouses_stats.country_notifier")
TOPIC = "DigitalHouses/Global/digitalhouses_stats/event/new_country"
COUNTRIES_SQL = text(
    """
    WITH first_seen AS (
        SELECT country, min(received_at) AS first_seen
        FROM heartbeats
        GROUP BY country
    ), latest AS (
        SELECT DISTINCT ON (product, installation_id)
            country
        FROM heartbeats
        ORDER BY product, installation_id, received_at DESC, id DESC
    )
    SELECT
        f.country,
        f.first_seen,
        (SELECT count(DISTINCT country) FROM latest) AS country_count
    FROM first_seen AS f
    WHERE f.country NOT IN ('ZZ', 'XX')
    ORDER BY f.first_seen, f.country
    """
)


def country_name(code: str) -> str:
    """Use Debian's standard ISO-3166 table, no external geolocation lookup."""
    path = Path("/usr/share/zoneinfo/iso3166.tab")
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            value, name = line.split("\t", 1)
            if value == code:
                return name
    except OSError:
        pass
    return code


def load_seen(path: Path) -> set[str] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("seen"), list):
        raise ValueError("invalid country notification state file")
    return set(data["seen"])


def save_seen(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temp = Path(handle.name)
        os.fchmod(handle.fileno(), 0o600)
        json.dump({"seen": sorted(seen)}, handle, ensure_ascii=False)
        handle.write("\n")
    os.replace(temp, path)


def publish_country(payload: dict[str, object]) -> None:
    host = os.environ["MQTT_HOST"]
    username = os.environ["MQTT_USERNAME"]
    password = os.environ["MQTT_PASSWORD"]
    port = int(os.getenv("MQTT_PORT", "1883"))
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(username, password)
    try:
        client.connect(host, port, keepalive=10)
        client.loop_start()
        info = client.publish(TOPIC, json.dumps(payload, ensure_ascii=False), qos=1, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish enqueue failed: {info.rc}")
        info.wait_for_publish(timeout=10)
        if not info.is_published():
            raise TimeoutError("MQTT broker did not acknowledge country notification")
    finally:
        client.disconnect()
        client.loop_stop()


def notify_rows(rows, state_file: Path, publish=publish_country) -> int:
    """Publish only unseen countries. Return the number of acknowledged events."""
    observed = {str(row["country"]) for row in rows}
    seen = load_seen(state_file)
    if seen is None:
        save_seen(state_file, observed)
        LOG.info("Initialized country notification baseline: %d countries", len(observed))
        return 0

    count = 0
    for row in rows:
        code = str(row["country"])
        if code in seen:
            continue
        payload = {
            "schema": 1,
            "event_type": "new_country",
            "country": code,
            "country_name": country_name(code),
            "country_count": int(row["country_count"]),
            "first_seen": row["first_seen"].isoformat(),
        }
        publish(payload)
        seen.add(code)
        save_seen(state_file, seen)
        count += 1
        LOG.info("Published new country %s; countries=%d", code, payload["country_count"])
    return count


def run() -> None:
    state_file = Path(os.getenv(
        "COUNTRY_STATE_FILE",
        "/var/lib/digitalhouses-stats/notified_countries.json",
    ))
    with engine.connect() as connection:
        rows = connection.execute(COUNTRIES_SQL).mappings().all()
    notify_rows(rows, state_file)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run()


if __name__ == "__main__":
    main()
