#!/usr/bin/with-contenv bashio
set -Eeuo pipefail
: "${APP_VERSION:?APP_VERSION required}"
if ! bashio::config.true 'telemetry_enabled'; then
    bashio::log.error "DigitalHouses telemetry consent is required for official App activation."
    exit 1
fi
export TZ="$(bashio::supervisor.timezone)"
export MQTT_HOST="$(bashio::services mqtt host)"
export MQTT_PORT="$(bashio::services mqtt port)"
export MQTT_USERNAME="$(bashio::services mqtt username)"
export MQTT_PASSWORD="$(bashio::services mqtt password)"
: "${MQTT_HOST:?MQTT service host required}"
: "${MQTT_PORT:?MQTT service port required}"
exec python3 /app/service.py
