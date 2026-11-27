#!/usr/bin/with-contenv bashio

set -Eeuo pipefail

if [[ -z "${APP_VERSION:-}" ]]; then
    bashio::log.fatal "APP_VERSION is required."
    exit 1
fi

bashio::log.info "Starting DigitalHouses Recorder App ${APP_VERSION}"

export TZ="$(bashio::supervisor.timezone)"
if [[ -z "${TZ}" ]]; then
    bashio::log.fatal "Supervisor timezone is unavailable."
    exit 1
fi

# Remove the legacy 0.1.0 polling group after upgrade. Internal medium/slow
# query cadences are no longer exposed in the user configuration.
OPTIONS_JSON="$(bashio::app.options)"
if bashio::jq.exists "${OPTIONS_JSON}" '.poll'; then
    bashio::log.info "Removing legacy 'poll' configuration option."
    bashio::app.option 'poll'
fi
if bashio::jq.exists "${OPTIONS_JSON}" '.timezone'; then
    bashio::log.info "Removing legacy 'timezone' configuration option."
    bashio::app.option 'timezone'
fi

export MQTT_HOST="$(bashio::services mqtt host)"
export MQTT_PORT="$(bashio::services mqtt port)"
export MQTT_USER="$(bashio::services mqtt username)"
export MQTT_PASSWORD="$(bashio::services mqtt password)"

if [[ -z "${MQTT_HOST}" || -z "${MQTT_PORT}" ]]; then
    bashio::log.fatal "MQTT service information is incomplete."
    exit 1
fi



# The Supervisor MySQL API is only relevant to MariaDB in supervisor mode.
# Querying it for PostgreSQL/manual MariaDB generates misleading API errors.
export MYSQL_SERVICE_HOST=""
export MYSQL_SERVICE_PORT=""
export MYSQL_SERVICE_USER=""
export MYSQL_SERVICE_PASSWORD=""

if [[ "$(bashio::config 'database_type')" == "mariadb" ]] &&
   [[ "$(bashio::config 'mariadb.connection' 'supervisor')" == "supervisor" ]]; then
    if MYSQL_HOST_VALUE="$(bashio::services mysql host 2>/dev/null)" && [[ -n "${MYSQL_HOST_VALUE}" ]]; then
        export MYSQL_SERVICE_HOST="${MYSQL_HOST_VALUE}"
        export MYSQL_SERVICE_PORT="$(bashio::services mysql port)"
        export MYSQL_SERVICE_USER="$(bashio::services mysql username)"
        export MYSQL_SERVICE_PASSWORD="$(bashio::services mysql password)"
        bashio::log.info "Supervisor MySQL service detected."
    else
        bashio::log.info "Supervisor MySQL service is not available; manual MariaDB mode remains available."
    fi
fi

# Keep the migration-only schema keys until all installed versions have
# had a chance to persist their chosen values. Remove them only after the
# atomic migration succeeds, never before.
if bashio::config.true 'telemetry_enabled'; then
    python3 /app/runtime_settings.py
    for key in publish_interval_minutes recorder_stale_seconds top_entities_limit; do
        if bashio::jq.exists "${OPTIONS_JSON}" ".${key}"; then
            bashio::app.option "${key}"
        fi
    done
fi

exec python3 /app/app.py
