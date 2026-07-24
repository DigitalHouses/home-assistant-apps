#!/usr/bin/with-contenv bashio

set -Eeuo pipefail

bashio::log.info "Starting DigitalHouses Speedtest ${APP_VERSION:-unknown}"

export MQTT_HOST="$(bashio::services mqtt host)"
export MQTT_PORT="$(bashio::services mqtt port)"
export MQTT_USER="$(bashio::services mqtt username)"
export MQTT_PASSWORD="$(bashio::services mqtt password)"

if [[ -z "${MQTT_HOST}" || -z "${MQTT_PORT}" ]]; then
    bashio::log.fatal "MQTT service information is incomplete."
    exit 1
fi

mkdir -p /data/.config /data/runtime
exec python3 /app/app.py
