#!/usr/bin/with-contenv bashio
set -Eeuo pipefail

if [[ -z "${APP_VERSION:-}" ]]; then
  bashio::log.fatal "APP_VERSION is required."
  exit 1
fi

export MQTT_HOST="$(bashio::services mqtt host)"
export MQTT_PORT="$(bashio::services mqtt port)"
export MQTT_USER="$(bashio::services mqtt username)"
export MQTT_PASSWORD="$(bashio::services mqtt password)"

if [[ -z "${MQTT_HOST}" || -z "${MQTT_PORT}" ]]; then
  bashio::log.fatal "MQTT service is required."
  exit 1
fi

bashio::log.warning "DH Sync 0.0.1 preview: inventory only. No YAML files will be modified."
exec python3 /app/app.py
