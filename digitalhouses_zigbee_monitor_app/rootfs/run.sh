#!/usr/bin/with-contenv bashio
set -Eeuo pipefail

: "${APP_VERSION:?APP_VERSION must be set}"
export TZ="$(bashio::supervisor.timezone)"
export MQTT_HOST="$(bashio::services mqtt host)"
export MQTT_PORT="$(bashio::services mqtt port)"
export MQTT_USER="$(bashio::services mqtt username)"
export MQTT_PASSWORD="$(bashio::services mqtt password)"

if [[ -z "${MQTT_HOST}" || -z "${MQTT_PORT}" ]]; then
    bashio::log.fatal "Supervisor MQTT service is not configured."
    exit 1
fi

mkdir -p /data
bashio::log.info "Starting DigitalHouses Zigbee Monitor App ${APP_VERSION}"
exec python3 /app/app.py
