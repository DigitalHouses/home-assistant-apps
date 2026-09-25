#!/usr/bin/with-contenv bashio

set -Eeuo pipefail

bashio::log.info "Starting DigitalHouses Internet App ${APP_VERSION:-unknown}"

export TZ="$(bashio::supervisor.timezone)"
export MQTT_HOST="$(bashio::services mqtt host)"
export MQTT_PORT="$(bashio::services mqtt port)"
export MQTT_USER="$(bashio::services mqtt username)"
export MQTT_PASSWORD="$(bashio::services mqtt password)"

if [[ -z "${MQTT_HOST}" || -z "${MQTT_PORT}" ]]; then
    bashio::log.fatal "MQTT service information is incomplete."
    exit 1
fi

MIGRATION_MODE="${DH_SLUG_MIGRATION_MODE:-}"
if [[ "${MIGRATION_MODE}" == "export" ]]; then
    if MIGRATION_MESSAGE="$(python3 /app/slug_migration.py export 2>&1)"; then
        bashio::log.info "${MIGRATION_MESSAGE}"
    else
        bashio::log.warning "Slug migration bridge export failed: ${MIGRATION_MESSAGE}"
    fi
elif [[ "${MIGRATION_MODE}" == "import" ]]; then
    if MIGRATION_MESSAGE="$(python3 /app/slug_migration.py import 2>&1)"; then
        bashio::log.info "${MIGRATION_MESSAGE}"
    else
        bashio::log.fatal "Slug migration import failed: ${MIGRATION_MESSAGE}"
        exit 1
    fi
fi

mkdir -p /data/runtime
exec python3 /app/app.py
