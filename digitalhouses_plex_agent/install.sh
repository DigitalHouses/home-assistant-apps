#!/usr/bin/env bash
set -euo pipefail

PRODUCT_ID="digitalhouses_plex_agent"
APP_NAME="${PRODUCT_ID}"
LEGACY_APP_NAME="digitalhouses_plex_monitoring"
SOURCE_PRODUCT_DIR="${PRODUCT_ID}"

SERVICE_NAME="${APP_NAME}.service"
GPU_SERVICE_NAME="${APP_NAME}_gpu_helper.service"
LEGACY_SERVICE_NAME="${LEGACY_APP_NAME}.service"
LEGACY_GPU_SERVICE_NAME="digitalhouses_plex_gpu_helper.service"

SERVICE_USER="${APP_NAME}"
SERVICE_GROUP="${APP_NAME}"
REPO_URL="https://github.com/DigitalHouses/home-assistant-apps.git"
RELEASE_IDENTIFIER="${PRODUCT_ID}"
SOURCE_REF="${DIGITALHOUSES_SOURCE_REF:-}"
ALLOW_NON_RELEASE_REF="${DIGITALHOUSES_ALLOW_NON_RELEASE_REF:-0}"
EXPECTED_VERSION=""

SEMVER_RE='(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)(-[0-9A-Za-z-]+([.][0-9A-Za-z-]+)*)?([+][0-9A-Za-z-]+([.][0-9A-Za-z-]+)*)?'

if [[ -z "${SOURCE_REF}" ]]; then
    echo "DIGITALHOUSES_SOURCE_REF is required."
    echo "Production installs must use: ${RELEASE_IDENTIFIER}-v<version>"
    exit 1
fi

if [[ "${SOURCE_REF}" =~ ^${RELEASE_IDENTIFIER}-v(${SEMVER_RE})$ ]]; then
    EXPECTED_VERSION="${BASH_REMATCH[1]}"
elif [[ "${ALLOW_NON_RELEASE_REF}" != "1" ]]; then
    echo "Ref ${SOURCE_REF} is not a canonical DigitalHouses Plex Agent release tag."
    echo "Production installs require: ${RELEASE_IDENTIFIER}-v<version>"
    echo "For explicit development/testing only, set DIGITALHOUSES_ALLOW_NON_RELEASE_REF=1."
    exit 1
else
    echo "WARNING: installing non-release source ref ${SOURCE_REF} (development/testing override)."
fi

APP_DIR="/opt/digitalhouses/${APP_NAME}"
CONFIG_DIR="/etc/${APP_NAME}"
CONFIG_FILE="${CONFIG_DIR}/${APP_NAME}.conf"
STATE_DIR="/var/lib/${APP_NAME}"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}"
GPU_UNIT_FILE="/etc/systemd/system/${GPU_SERVICE_NAME}"
PLEX_LOCAL_ADMIN_TOKEN="/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/.LocalAdminToken"
PLEX_API_TOKEN_FILE="${CONFIG_DIR}/plex_local_admin_token"
TOKEN_DROPIN_DIR="/etc/systemd/system/${SERVICE_NAME}.d"
TOKEN_DROPIN_FILE="${TOKEN_DROPIN_DIR}/plex-local-token.conf"

LEGACY_APP_DIR="/opt/digitalhouses/${LEGACY_APP_NAME}"
LEGACY_CONFIG_DIR="/etc/${LEGACY_APP_NAME}"
LEGACY_CONFIG_FILE="${LEGACY_CONFIG_DIR}/${LEGACY_APP_NAME}.conf"
LEGACY_STATE_DIR="/var/lib/${LEGACY_APP_NAME}"
LEGACY_TOKEN_FILE="${LEGACY_CONFIG_DIR}/plex_local_admin_token"
LEGACY_UNIT_FILE="/etc/systemd/system/${LEGACY_SERVICE_NAME}"
LEGACY_GPU_UNIT_FILE="/etc/systemd/system/${LEGACY_GPU_SERVICE_NAME}"
LEGACY_TOKEN_DROPIN_DIR="/etc/systemd/system/${LEGACY_SERVICE_NAME}.d"
LEGACY_TOKEN_DROPIN_FILE="${LEGACY_TOKEN_DROPIN_DIR}/plex-local-token.conf"

MIGRATION_MARKER="${STATE_DIR}/.runtime_migrated_from_${LEGACY_APP_NAME}"
MIGRATION_IN_PROGRESS="${STATE_DIR}/.runtime_migration_in_progress"
BACKUP_DIR="/var/backups/${APP_NAME}"

if [[ "${EUID}" -ne 0 ]]; then
    echo "This installer must run as root."
    echo "See the product README for the canonical release-tag install command."
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

intel_gpu_present=0
for vendor_path in /sys/class/drm/renderD*/device/vendor; do
    if [[ -r "${vendor_path}" ]] && grep -qi '0x8086' "${vendor_path}"; then
        intel_gpu_present=1
        break
    fi
done

if [[ "${intel_gpu_present}" -eq 1 ]] && ! command -v intel_gpu_top >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        echo "Intel GPU detected; installing optional intel-gpu-tools telemetry dependency."
        if ! apt-get update || ! DEBIAN_FRONTEND=noninteractive apt-get install -y intel-gpu-tools; then
            echo "Warning: unable to install intel-gpu-tools; GPU telemetry will remain unavailable."
        fi
    else
        echo "Warning: Intel GPU detected but intel_gpu_top is unavailable."
    fi
fi

tmp_dir="$(mktemp -d)"
cleanup() {
    rm -rf "${tmp_dir}"
}
trap cleanup EXIT

echo "Fetching DigitalHouses source ref: ${SOURCE_REF}"
git clone --quiet --filter=blob:none --no-checkout "${REPO_URL}" "${tmp_dir}/repo"

if [[ -n "${EXPECTED_VERSION}" ]]; then
    git -C "${tmp_dir}/repo" fetch --quiet --depth 1 origin \
        "refs/tags/${SOURCE_REF}:refs/tags/${SOURCE_REF}"
    git -C "${tmp_dir}/repo" checkout --quiet --detach "refs/tags/${SOURCE_REF}"
else
    git -C "${tmp_dir}/repo" fetch --quiet --depth 1 origin "${SOURCE_REF}"
    git -C "${tmp_dir}/repo" checkout --quiet --detach FETCH_HEAD
fi

SOURCE_SHA="$(git -C "${tmp_dir}/repo" rev-parse HEAD)"
SOURCE_APP="${tmp_dir}/repo/${SOURCE_PRODUCT_DIR}"

if [[ ! -f "${SOURCE_APP}/VERSION" ]]; then
    echo "Application ${SOURCE_PRODUCT_DIR} not found at source ref ${SOURCE_REF}."
    exit 1
fi

SOURCE_VERSION="$(tr -d '[:space:]' <"${SOURCE_APP}/VERSION")"
if [[ -n "${EXPECTED_VERSION}" && "${SOURCE_VERSION}" != "${EXPECTED_VERSION}" ]]; then
    echo "Release tag/version mismatch: ${SOURCE_REF} contains VERSION=${SOURCE_VERSION}."
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

for supplemental_group in render video; do
    if getent group "${supplemental_group}" >/dev/null 2>&1; then
        usermod -a -G "${supplemental_group}" "${SERVICE_USER}"
    fi
done

install -d -o root -g root -m 0755 /opt/digitalhouses
install -d -o root -g root -m 0755 "${APP_DIR}"
install -d -o root -g "${SERVICE_GROUP}" -m 0750 "${CONFIG_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 "${STATE_DIR}"

legacy_runtime_present=0
for legacy_path in \
    "${LEGACY_CONFIG_FILE}" \
    "${LEGACY_STATE_DIR}" \
    "${LEGACY_UNIT_FILE}" \
    "${LEGACY_GPU_UNIT_FILE}"; do
    if [[ -e "${legacy_path}" ]]; then
        legacy_runtime_present=1
        break
    fi
done

migration_performed=0
legacy_main_was_enabled=0
legacy_main_was_active=0
legacy_gpu_was_enabled=0
legacy_gpu_was_active=0

if [[ "${legacy_runtime_present}" -eq 1 && ! -f "${MIGRATION_MARKER}" ]]; then
    if [[ ! -f "${MIGRATION_IN_PROGRESS}" ]]; then
        canonical_state_entry="$(
            find "${STATE_DIR}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null || true
        )"
        if [[ -f "${CONFIG_FILE}" || -n "${canonical_state_entry}" ]]; then
            echo "Refusing automatic runtime migration: canonical Plex Agent config/state already exists."
            echo "Resolve ${CONFIG_DIR} and ${STATE_DIR} manually before retrying."
            exit 1
        fi
    fi

    echo
    echo "Migrating legacy Plex runtime identity to ${APP_NAME}."

    systemctl is-enabled --quiet "${LEGACY_SERVICE_NAME}" 2>/dev/null && legacy_main_was_enabled=1 || true
    systemctl is-active --quiet "${LEGACY_SERVICE_NAME}" 2>/dev/null && legacy_main_was_active=1 || true
    systemctl is-enabled --quiet "${LEGACY_GPU_SERVICE_NAME}" 2>/dev/null && legacy_gpu_was_enabled=1 || true
    systemctl is-active --quiet "${LEGACY_GPU_SERVICE_NAME}" 2>/dev/null && legacy_gpu_was_active=1 || true

    systemctl disable --now "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1 || true
    systemctl disable --now "${LEGACY_GPU_SERVICE_NAME}" >/dev/null 2>&1 || true

    touch "${MIGRATION_IN_PROGRESS}"

    install -d -o root -g root -m 0700 "${BACKUP_DIR}"
    backup_stamp="$(date '+%Y%m%d_%H%M%S')"
    backup_file="${BACKUP_DIR}/legacy-runtime-${backup_stamp}.tar.gz"
    backup_paths=()
    for legacy_path in \
        "${LEGACY_CONFIG_DIR}" \
        "${LEGACY_STATE_DIR}" \
        "${LEGACY_UNIT_FILE}" \
        "${LEGACY_GPU_UNIT_FILE}"; do
        if [[ -e "${legacy_path}" ]]; then
            backup_paths+=("${legacy_path#/}")
        fi
    done
    if [[ "${#backup_paths[@]}" -gt 0 ]]; then
        tar -C / -czf "${backup_file}" "${backup_paths[@]}"
        chmod 0600 "${backup_file}"
        echo "Legacy runtime backup: ${backup_file}"
    fi

    if [[ -f "${LEGACY_CONFIG_FILE}" ]]; then
        cp -a "${LEGACY_CONFIG_FILE}" "${CONFIG_FILE}"
        sed -i -E \
            's#^([[:space:]]*token_file[[:space:]]*=[[:space:]]*)/etc/digitalhouses_plex_monitoring/plex_local_admin_token[[:space:]]*$#\1/etc/digitalhouses_plex_agent/plex_local_admin_token#' \
            "${CONFIG_FILE}"
    fi

    if [[ -f "${LEGACY_TOKEN_FILE}" ]]; then
        cp -a "${LEGACY_TOKEN_FILE}" "${PLEX_API_TOKEN_FILE}"
    fi

    if [[ -d "${LEGACY_STATE_DIR}" ]]; then
        cp -a "${LEGACY_STATE_DIR}/." "${STATE_DIR}/"
    fi

    {
        printf 'migrated_at=%s\n' "$(date --iso-8601=seconds)"
        printf 'source_runtime=%s\n' "${LEGACY_APP_NAME}"
        printf 'target_runtime=%s\n' "${APP_NAME}"
        printf 'source_release=%s\n' "${SOURCE_REF}"
    } >"${MIGRATION_MARKER}"
    rm -f "${MIGRATION_IN_PROGRESS}"
    migration_performed=1
fi

# Replace installed source while preserving the canonical virtual environment.
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
        printf 'token_file = %s\n' "${PLEX_API_TOKEN_FILE}"
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

if [[ -f "${PLEX_LOCAL_ADMIN_TOKEN}" ]]; then
    install -o root -g "${SERVICE_GROUP}" -m 0640 \
        "${PLEX_LOCAL_ADMIN_TOKEN}" "${PLEX_API_TOKEN_FILE}"
elif [[ -f "${PLEX_API_TOKEN_FILE}" ]]; then
    chown root:"${SERVICE_GROUP}" "${PLEX_API_TOKEN_FILE}"
    chmod 0640 "${PLEX_API_TOKEN_FILE}"
else
    echo "Warning: Plex .LocalAdminToken was not found; Plex API monitoring will remain unavailable."
fi

chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${STATE_DIR}"
chmod 0750 "${STATE_DIR}"
if [[ -f "${MIGRATION_MARKER}" ]]; then
    chown root:root "${MIGRATION_MARKER}"
    chmod 0644 "${MIGRATION_MARKER}"
fi

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

VERSION="${SOURCE_VERSION}"
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
install -o root -g root -m 0644 \
    "${APP_DIR}/systemd/${GPU_SERVICE_NAME}" \
    "${GPU_UNIT_FILE}"

# 0.2.0 used a systemd LoadCredential drop-in. Remove both historical and
# canonical locations during upgrade.
rm -f "${TOKEN_DROPIN_FILE}" "${LEGACY_TOKEN_DROPIN_FILE}"
rmdir "${TOKEN_DROPIN_DIR}" "${LEGACY_TOKEN_DROPIN_DIR}" 2>/dev/null || true

systemctl daemon-reload

if [[ "${intel_gpu_present}" -eq 1 ]] && command -v intel_gpu_top >/dev/null 2>&1; then
    systemctl enable "${GPU_SERVICE_NAME}" >/dev/null
    if ! systemctl restart "${GPU_SERVICE_NAME}"; then
        echo "Warning: DigitalHouses Plex Agent GPU Helper failed to start; GPU telemetry will remain unavailable."
        systemctl status "${GPU_SERVICE_NAME}" --no-pager || true
        journalctl -u "${GPU_SERVICE_NAME}" -n 50 --no-pager || true
    fi
else
    systemctl disable --now "${GPU_SERVICE_NAME}" >/dev/null 2>&1 || true
    rm -f "${STATE_DIR}/gpu_state.json"
fi

systemctl enable "${SERVICE_NAME}" >/dev/null
systemctl restart "${SERVICE_NAME}"

if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "DigitalHouses Plex Agent failed to start."
    systemctl status "${SERVICE_NAME}" --no-pager || true
    journalctl -u "${SERVICE_NAME}" -n 50 --no-pager || true

    if [[ "${migration_performed}" -eq 1 ]]; then
        echo "Canonical runtime failed; restoring the previous legacy service state."
        systemctl disable --now "${SERVICE_NAME}" >/dev/null 2>&1 || true
        systemctl disable --now "${GPU_SERVICE_NAME}" >/dev/null 2>&1 || true

        if [[ "${legacy_gpu_was_enabled}" -eq 1 ]]; then
            systemctl enable "${LEGACY_GPU_SERVICE_NAME}" >/dev/null 2>&1 || true
        fi
        if [[ "${legacy_gpu_was_active}" -eq 1 ]]; then
            systemctl start "${LEGACY_GPU_SERVICE_NAME}" >/dev/null 2>&1 || true
        fi
        if [[ "${legacy_main_was_enabled}" -eq 1 ]]; then
            systemctl enable "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1 || true
        fi
        if [[ "${legacy_main_was_active}" -eq 1 ]]; then
            systemctl start "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1 || true
        fi
    fi
    exit 1
fi

echo
echo "DigitalHouses Plex Agent installed successfully."
echo "Version: ${VERSION}"
echo "Source: ${SOURCE_REF}"
echo "Commit: ${SOURCE_SHA}"
echo "Config: ${CONFIG_FILE}"
echo "Status: systemctl status ${APP_NAME}"
if [[ "${migration_performed}" -eq 1 ]]; then
    echo "Legacy runtime retained for rollback: ${LEGACY_CONFIG_DIR}, ${LEGACY_STATE_DIR}"
fi
if [[ "${intel_gpu_present}" -eq 1 ]] && command -v intel_gpu_top >/dev/null 2>&1; then
    echo "GPU helper: systemctl status ${GPU_SERVICE_NAME}"
fi
