#!/usr/bin/with-contenv bashio
set -Eeuo pipefail

: "${APP_VERSION:?APP_VERSION is required}"
export DH_PORT="$(bashio::app.ingress_port)"
export DH_DB="/data/network.sqlite3"
export DH_INTERVAL="$(bashio::config 'poll_interval_seconds')"
export DH_SCAN_INTERVAL="$(bashio::config 'scan_interval_seconds')"
export DH_MDNS_INTERVAL="$(bashio::config 'mdns_interval_seconds')"
export DH_SSDP_INTERVAL="$(bashio::config 'ssdp_interval_seconds')"
export DH_WSD_INTERVAL="$(bashio::config 'wsd_interval_seconds')"

export DH_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export MQTT_HOST=""
export MQTT_PORT="1883"
export MQTT_USER=""
export MQTT_PASSWORD=""
if bashio::services.available mqtt; then
    export MQTT_HOST="$(bashio::services mqtt host)"
    export MQTT_PORT="$(bashio::services mqtt port)"
    export MQTT_USER="$(bashio::services mqtt username)"
    export MQTT_PASSWORD="$(bashio::services mqtt password)"
fi

python3 /app/preflight.py
bashio::log.info "Starting DigitalHouses Network App ${APP_VERSION} on Ingress port ${DH_PORT}"
# MQTT publisher is a separate optional worker. The Go scanner and Ingress
# remain usable if the broker is unavailable or the worker exits.
python3 /app/mqtt_events.py &
exec /usr/local/bin/dh-network
