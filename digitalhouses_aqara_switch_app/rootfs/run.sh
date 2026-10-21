#!/usr/bin/with-contenv bashio
set -Eeuo pipefail
: "${APP_VERSION:?APP_VERSION must be set}"
exec python3 /app/app.py
