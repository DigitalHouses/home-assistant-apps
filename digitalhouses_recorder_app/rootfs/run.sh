#!/usr/bin/with-contenv bashio

set -Eeuo pipefail

bashio::log.info "Starting DigitalHouses DB Monitoring ${APP_VERSION:-unknown}"

# Remove the legacy 0.1.0 polling group after upgrade. Internal medium/slow
# query cadences are no longer exposed in the user configuration.
OPTIONS_JSON="$(bashio::addon.options)"
if bashio::jq.exists "${OPTIONS_JSON}" '.poll'; then
    bashio::log.info "Removing legacy 'poll' configuration option."
    bashio::addon.option 'poll'
fi

export MQTT_HOST="$(bashio::services mqtt host)"
export MQTT_PORT="$(bashio::services mqtt port)"
export MQTT_USER="$(bashio::services mqtt username)"
export MQTT_PASSWORD="$(bashio::services mqtt password)"

if [[ -z "${MQTT_HOST}" || -z "${MQTT_PORT}" ]]; then
    bashio::log.fatal "MQTT service information is incomplete."
    exit 1
fi

if MYSQL_HOST_VALUE="$(bashio::services mysql host 2>/dev/null)" && [[ -n "${MYSQL_HOST_VALUE}" ]]; then
    export MYSQL_SERVICE_HOST="${MYSQL_HOST_VALUE}"
    export MYSQL_SERVICE_PORT="$(bashio::services mysql port)"
    export MYSQL_SERVICE_USER="$(bashio::services mysql username)"
    export MYSQL_SERVICE_PASSWORD="$(bashio::services mysql password)"
    bashio::log.info "Supervisor MySQL service detected."
else
    export MYSQL_SERVICE_HOST=""
    export MYSQL_SERVICE_PORT=""
    export MYSQL_SERVICE_USER=""
    export MYSQL_SERVICE_PASSWORD=""
    bashio::log.info "Supervisor MySQL service is not available; manual MariaDB mode remains available."
fi

exec python3 /app/app.py
