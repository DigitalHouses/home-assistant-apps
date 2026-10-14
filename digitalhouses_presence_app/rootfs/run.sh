#!/usr/bin/with-contenv bashio
set -Eeuo pipefail

: "${APP_VERSION:?APP_VERSION required}"
bashio::log.info "Starting DigitalHouses Presence App ${APP_VERSION}"
# Home Assistant Core API is enabled, but unrestricted Supervisor API is not.
# Never call bashio::supervisor.timezone here: it needs Supervisor API
# permissions which this GPS/MQTT pilot does not require.
# DigitalHouses Home Assistant installations use Asia/Almaty local time.
export TZ="${TZ:-Asia/Almaty}"
export MQTT_HOST="$(bashio::services mqtt host)"
export MQTT_PORT="$(bashio::services mqtt port)"
export MQTT_USER="$(bashio::services mqtt username)"
export MQTT_PASSWORD="$(bashio::services mqtt password)"
export LOG_LEVEL="$(bashio::config 'log_level')"
: "${SUPERVISOR_TOKEN:?Home Assistant API token required}"
: "${MQTT_HOST:?MQTT service required}"
: "${MQTT_PORT:?MQTT port required}"
mkdir -p /data
exec python3 /app/app.py
