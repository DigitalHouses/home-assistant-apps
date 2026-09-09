#!/usr/bin/env bash
set -euo pipefail

APP_NAME="digitalhouses_plex_monitoring"
SERVICE_NAME="${APP_NAME}.service"
SERVICE_USER="${APP_NAME}"
SERVICE_GROUP="${APP_NAME}"
REPO_URL="https://github.com/DigitalHouses/home-assistant-apps.git"
SOURCE_REF="${DIGITALHOUSES_SOURCE_REF:-main}"

APP_DIR="/opt/digitalhouses/${APP_NAME}"
CONFIG_DIR="/etc/${APP_NAME}"
CONFIG_FILE="${CONFIG_DIR}/${APP_NAME}.conf"
STATE_DIR="/var/lib/${APP_NAME}"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}"
PLEX_LOCAL_ADMIN_TOKEN="/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/.LocalAdminToken"
TOKEN_DROPIN_DIR="/etc/systemd/system/${SERVICE_NAME}.d"
TOKEN_DROPIN_FILE="${TOKEN_DROPIN_DIR}/plex-local-token.conf"

if [[ "${EUID}" -ne 0 ]]; then
    echo "This installer must run as root."
    echo "Example: curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/${APP_NAME}/install.sh | sudo bash"
    exit 1
fi

need_apt=0
command -v git >/dev/null 2>&1 || need_apt=1
command -v python3 >/dev/null 2>&1 || need_apt=1
python3 -m venv --help >/dev/null 2>&1 || need_apt=1

if [[ "${need_apt}" -eq 1 ]]; then
    if ! command -v apt-get >/dev/null 2>&1; then
        echo "Missing prerequisites and apt-get is unavailable."
        echo "Initial supported installer targets are Debian/Ubuntu-family systems."
        exit 1
    fi
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        ca-certificates \
        git \
        python3 \
        python3-venv
fi

tmp_dir="$(mktemp -d)"
cleanup() {
    rm -rf "${tmp_dir}"
}
trap cleanup EXIT

echo "Fetching DigitalHouses source ref: ${SOURCE_REF}"
git clone --quiet --filter=blob:none --no-checkout "${REPO_URL}" "${tmp_dir}/repo"
git -C "${tmp_dir}/repo" fetch --quiet --depth 1 origin "${SOURCE_REF}"
git -C "${tmp_dir}/repo" checkout --quiet --detach FETCH_HEAD

SOURCE_SHA="$(git -C "${tmp_dir}/repo" rev-parse HEAD)"
SOURCE_APP="${tmp_dir}/repo/${APP_NAME}"

if [[ ! -f "${SOURCE_APP}/VERSION" ]]; then
    echo "Application ${APP_NAME} not found at source ref ${SOURCE_REF}."
    exit 1
fi

if ! getent group "${SERVICE_GROUP}" >/dev/null 2>&1; then
    groupadd --system "${SERVICE_GROUP}"
fi
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd \
        --system \
        --gid "${SERVICE_GROUP}" \
        --home-dir "${STATE_DIR}" \
        --no-create-home \
        --shell /usr/sbin/nologin \
        "${SERVICE_USER}"
fi

install -d -o root -g root -m 0755 /opt/digitalhouses
install -d -o root -g root -m 0755 "${APP_DIR}"
install -d -o root -g "${SERVICE_GROUP}" -m 0750 "${CONFIG_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 "${STATE_DIR}"

# Replace installed source while preserving the virtual environment.
find "${APP_DIR}" \
    -mindepth 1 -maxdepth 1 \
    ! -name ".venv" \
    -exec rm -rf -- {} +
cp -a "${SOURCE_APP}/." "${APP_DIR}/"
chown -R root:root "${APP_DIR}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
    if [[ ! -r /dev/tty ]]; then
        echo "First installation requires an interactive terminal for MQTT settings."
        exit 1
    fi

    instance_id="${DIGITALHOUSES_INSTANCE_ID:-plex}"
    instance_name="${DIGITALHOUSES_INSTANCE_NAME:-$(hostname -s)}"
    mqtt_port="1883"
    mqtt_host=""
    mqtt_user=""
    mqtt_password=""

    while [[ -z "${mqtt_host}" ]]; do
        printf "MQTT host: " >/dev/tty
        IFS= read -r mqtt_host </dev/tty
    done

    printf "MQTT port [1883]: " >/dev/tty
    IFS= read -r answer </dev/tty
    [[ -n "${answer}" ]] && mqtt_port="${answer}"

    printf "MQTT username [optional]: " >/dev/tty
    IFS= read -r mqtt_user </dev/tty

    printf "MQTT password [optional]: " >/dev/tty
    IFS= read -r -s mqtt_password </dev/tty
    printf "\n" >/dev/tty

    previous_umask="$(umask)"
    umask 0027
    {
        printf '%s\n' "[general]"
        printf 'instance_id = %s\n' "${instance_id}"
        printf 'instance_name = %s\n' "${instance_name}"
        printf '%s\n' "poll_interval_seconds = 10"
        printf '%s\n' "cpu_window_seconds = 60"
        printf '%s\n' "log_level = info"
        printf '\n'
        printf '%s\n' "[telemetry]"
        printf '%s\n' "cpu_change_threshold = 5"
        printf '%s\n' "high_load_threshold = 80"
        printf '%s\n' "high_load_publish_interval_seconds = 60"
        printf '\n'
        printf '%s\n' "[plex_api]"
        printf '%s\n' "enabled = true"
        printf '%s\n' "base_url = http://127.0.0.1:32400"
        printf '%s\n' "timeout_seconds = 3"
        printf '%s\n' "library_refresh_seconds = 3600"
        printf '\n'
        printf '%s\n' "[mqtt]"
        printf 'host = %s\n' "${mqtt_host}"
        printf 'port = %s\n' "${mqtt_port}"
        printf 'username = %s\n' "${mqtt_user}"
        printf 'password = %s\n' "${mqtt_password}"
        printf '%s\n' "topic_prefix = DigitalHouses/Global/plex_monitoring"
        printf '%s\n' "discovery_prefix = homeassistant"
        printf '%s\n' "keepalive_seconds = 60"
    } >"${CONFIG_FILE}"
    umask "${previous_umask}"
fi

chown root:"${SERVICE_GROUP}" "${CONFIG_FILE}"
chmod 0640 "${CONFIG_FILE}"

if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
    python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/python" -m pip install \
    --disable-pip-version-check \
    --upgrade pip
"${APP_DIR}/.venv/bin/python" -m pip install \
    --disable-pip-version-check \
    -r "${APP_DIR}/requirements.txt"
chmod -R a+rX "${APP_DIR}/.venv"

PYTHONPATH="${APP_DIR}" "${APP_DIR}/.venv/bin/python" -c \
    'from pathlib import Path; from app.config import load_config; load_config(Path("'"${CONFIG_FILE}"'"))'
"${APP_DIR}/.venv/bin/python" -m compileall -q "${APP_DIR}/app"

VERSION="$(tr -d '[:space:]' <"${APP_DIR}/VERSION")"
{
    printf 'version = %s\n' "${VERSION}"
    printf 'source = %s\n' "${SOURCE_REF}"
    printf 'commit = %s\n' "${SOURCE_SHA}"
} >"${APP_DIR}/BUILD_INFO"
chown root:root "${APP_DIR}/BUILD_INFO"
chmod 0644 "${APP_DIR}/BUILD_INFO"

install -o root -g root -m 0644 \
    "${APP_DIR}/systemd/${SERVICE_NAME}" \
    "${UNIT_FILE}"

if [[ -f "${PLEX_LOCAL_ADMIN_TOKEN}" ]]; then
    install -d -o root -g root -m 0755 "${TOKEN_DROPIN_DIR}"
    {
        printf '%s\n' "[Service]"
        printf 'LoadCredential="plex_local_admin_token:%s"\n' "${PLEX_LOCAL_ADMIN_TOKEN}"
    } >"${TOKEN_DROPIN_FILE}"
    chown root:root "${TOKEN_DROPIN_FILE}"
    chmod 0644 "${TOKEN_DROPIN_FILE}"
else
    rm -f "${TOKEN_DROPIN_FILE}"
fi

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" >/dev/null
systemctl restart "${SERVICE_NAME}"

if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "DigitalHouses Plex Monitoring failed to start."
    systemctl status "${SERVICE_NAME}" --no-pager || true
    journalctl -u "${SERVICE_NAME}" -n 50 --no-pager || true
    exit 1
fi

echo
echo "DigitalHouses Plex Monitoring installed successfully."
echo "Version: ${VERSION}"
echo "Source: ${SOURCE_REF}"
echo "Commit: ${SOURCE_SHA}"
echo "Config: ${CONFIG_FILE}"
echo "Status: systemctl status ${APP_NAME}"
