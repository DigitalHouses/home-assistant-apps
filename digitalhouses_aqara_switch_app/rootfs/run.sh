#!/usr/bin/with-contenv bashio
set -Eeuo pipefail

: "${APP_VERSION:?APP_VERSION must be set}"
export TZ="$(bashio::supervisor.timezone)"
export MQTT_HOST="$(bashio::services mqtt host)"
export MQTT_PORT="$(bashio::services mqtt port)"
export MQTT_USER="$(bashio::services mqtt username)"
export MQTT_PASSWORD="$(bashio::services mqtt password)"
: "${MQTT_HOST:?MQTT_HOST must be configured}"
: "${MQTT_PORT:?MQTT_PORT must be configured}"
: "${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN must be configured}"
mkdir -p /data
bashio::log.info "Aqara Switch App v${APP_VERSION}: manual-scan + optional passive light monitor, no relay writes"
exec python3 /app/app.py
