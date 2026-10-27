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

python3 /app/preflight.py
bashio::log.info "Starting DigitalHouses Network App ${APP_VERSION} on Ingress port ${DH_PORT}"
exec /usr/local/bin/dh-network
