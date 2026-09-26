#!/usr/bin/env bash
set -euo pipefail

PRODUCT_ID="digitalhouses_pve_agent"
APP_NAME="${PRODUCT_ID}"
SOURCE_PRODUCT_DIR="${PRODUCT_ID}"
SERVICE_NAME="${PRODUCT_ID}.service"
REPO_URL="https://github.com/DigitalHouses/home-assistant-apps.git"
INSTALL_MODE="${DIGITALHOUSES_INSTALL_MODE:-production}"
SOURCE_REF="${DIGITALHOUSES_SOURCE_REF:-}"

APP_DIR="/opt/digitalhouses/${PRODUCT_ID}"
CONFIG_DIR="/etc/${PRODUCT_ID}"
CONFIG_FILE="${CONFIG_DIR}/${PRODUCT_ID}.conf"
STATE_DIR="/var/lib/${PRODUCT_ID}"
TELEMETRY_STATE_DIR="/var/lib/digitalhouses/${PRODUCT_ID}"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}"
ROOT_GUIDE="/root/digitalhouses_pve_agent.txt"
CANONICAL_TOPIC_PREFIX="DigitalHouses/Global/digitalhouses_pve_agent"

LEGACY_APP_NAME="dh_pve_app"
LEGACY_SERVICE_NAME="${LEGACY_APP_NAME}.service"
LEGACY_APP_DIR="/opt/digitalhouses/${LEGACY_APP_NAME}"
LEGACY_CONFIG_DIR="/etc/${LEGACY_APP_NAME}"
LEGACY_CONFIG_FILE="${LEGACY_CONFIG_DIR}/${LEGACY_APP_NAME}.conf"
LEGACY_STATE_DIR="/var/lib/${LEGACY_APP_NAME}"
LEGACY_UNIT_FILE="/etc/systemd/system/${LEGACY_SERVICE_NAME}"
LEGACY_ROOT_GUIDE="/root/dh_app_pve.txt"
LEGACY_TOPIC_PREFIX="DigitalHouses/Global/dh_pve_app"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Установщик должен быть запущен от root."
    echo "Production installer должен запускаться из canonical release tag."
    exit 1
fi

if ! command -v pveversion >/dev/null 2>&1 || [[ ! -d /etc/pve ]]; then
    echo "Ошибка: этот установщик предназначен для Proxmox VE."
    exit 1
fi

if [[ ! -r /etc/machine-id ]]; then
    echo "Ошибка: /etc/machine-id отсутствует или недоступен."
    exit 1
fi

case "${INSTALL_MODE}" in
    production)
        if [[ -z "${SOURCE_REF}" ]]; then
            echo "Ошибка: production install требует DIGITALHOUSES_SOURCE_REF=<canonical release tag>."
            exit 2
        fi
        if [[ ! "${SOURCE_REF}" =~ ^digitalhouses_pve_agent-v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
            echo "Ошибка: production source ref должен быть canonical release tag digitalhouses_pve_agent-v<version>."
            exit 2
        fi
        ;;
    development|recovery)
        if [[ -z "${SOURCE_REF}" ]]; then
            echo "Ошибка: ${INSTALL_MODE} mode требует явный DIGITALHOUSES_SOURCE_REF."
            exit 2
        fi
        ;;
    *)
        echo "Ошибка: DIGITALHOUSES_INSTALL_MODE должен быть production, development или recovery."
        exit 2
        ;;
esac

need_apt=0
for command_name in git curl tar python3 smartctl lspci dmidecode; do
    command -v "${command_name}" >/dev/null 2>&1 || need_apt=1
done
if ! dpkg-query -W -f='${Status}\n' python3-venv 2>/dev/null \
    | grep -q 'install ok installed'; then
    need_apt=1
fi

if [[ "${need_apt}" -eq 1 ]]; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        ca-certificates \
        git \
        curl \
        tar \
        python3 \
        python3-venv \
        smartmontools \
        pciutils \
        dmidecode
fi

if ! command -v intel_gpu_top >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y intel-gpu-tools >/dev/null 2>&1 || true
fi

tmp_dir="$(mktemp -d)"
cleanup() {
    rm -rf "${tmp_dir}"
}
trap cleanup EXIT

echo "Получение DigitalHouses source ref: ${SOURCE_REF}"

if [[ "${SOURCE_REF}" =~ ^[0-9a-fA-F]{40}$ ]]; then
    archive="${tmp_dir}/source.tar.gz"
    install -d -m 0755 "${tmp_dir}/repo"

    echo "Используется immutable codeload archive для exact SHA."
    curl -fsSL \
        --retry 3 \
        --retry-delay 2 \
        --connect-timeout 10 \
        --max-time 120 \
        "https://codeload.github.com/DigitalHouses/home-assistant-apps/tar.gz/${SOURCE_REF}" \
        -o "${archive}"

    tar -xzf "${archive}" --strip-components=1 -C "${tmp_dir}/repo"
    SOURCE_SHA="${SOURCE_REF}"
else
    git clone --quiet --filter=blob:none --no-checkout "${REPO_URL}" "${tmp_dir}/repo"
    git -C "${tmp_dir}/repo" fetch --quiet --depth 1 origin "${SOURCE_REF}"
    git -C "${tmp_dir}/repo" checkout --quiet --detach FETCH_HEAD
    SOURCE_SHA="$(git -C "${tmp_dir}/repo" rev-parse HEAD)"
fi

SOURCE_APP="${tmp_dir}/repo/${SOURCE_PRODUCT_DIR}"

if [[ ! -f "${SOURCE_APP}/VERSION" ]]; then
    echo "Ошибка: ${SOURCE_PRODUCT_DIR} не найден в source ref ${SOURCE_REF}."
    exit 1
fi

SOURCE_VERSION="$(tr -d '[:space:]' <"${SOURCE_APP}/VERSION")"
if [[ -z "${SOURCE_VERSION}" ]]; then
    echo "Ошибка: VERSION пуст."
    exit 1
fi
if [[ "${INSTALL_MODE}" == "production" ]]; then
    EXPECTED_SOURCE_REF="${PRODUCT_ID}-v${SOURCE_VERSION}"
    if [[ "${SOURCE_REF}" != "${EXPECTED_SOURCE_REF}" ]]; then
        echo "Ошибка: release tag ${SOURCE_REF} не соответствует VERSION=${SOURCE_VERSION}."
        echo "Ожидается: ${EXPECTED_SOURCE_REF}"
        exit 1
    fi
fi

legacy_runtime_detected=0
legacy_was_active=0
legacy_was_enabled=0
if systemctl cat "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1 \
    || [[ -d "${LEGACY_APP_DIR}" || -f "${LEGACY_CONFIG_FILE}" || -d "${LEGACY_STATE_DIR}" ]]; then
    legacy_runtime_detected=1
    if [[ -d "${APP_DIR}" || -f "${CONFIG_FILE}" || -d "${STATE_DIR}" || -e "${UNIT_FILE}" ]]; then
        echo "Ошибка: одновременно обнаружены legacy и canonical runtime."
        echo "Legacy: ${LEGACY_APP_NAME}; canonical: ${PRODUCT_ID}."
        echo "Автоматическая миграция остановлена, чтобы не смешивать state/config."
        exit 1
    fi
    systemctl is-active --quiet "${LEGACY_SERVICE_NAME}" && legacy_was_active=1 || true
    systemctl is-enabled --quiet "${LEGACY_SERVICE_NAME}" && legacy_was_enabled=1 || true
    if systemctl cat "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1; then
        echo "Остановка legacy runtime: ${LEGACY_SERVICE_NAME}"
        systemctl stop "${LEGACY_SERVICE_NAME}"
    fi
fi

install -d -o root -g root -m 0755 /opt/digitalhouses
install -d -o root -g root -m 0755 "${APP_DIR}"
install -d -o root -g root -m 0750 "${CONFIG_DIR}"
install -d -o root -g root -m 0750 "${STATE_DIR}"
install -d -o root -g root -m 0700 "${TELEMETRY_STATE_DIR}"

if [[ "${legacy_runtime_detected}" -eq 1 ]]; then
    echo "Миграция legacy runtime -> ${PRODUCT_ID}"

    if [[ -f "${LEGACY_CONFIG_FILE}" ]]; then
        cp -a "${LEGACY_CONFIG_FILE}" "${CONFIG_FILE}"
        sed -i -E \
            "s|^([[:space:]]*topic_prefix[[:space:]]*=[[:space:]]*)${LEGACY_TOPIC_PREFIX}([[:space:]]*)$|\\1${CANONICAL_TOPIC_PREFIX}\\2|" \
            "${CONFIG_FILE}"
    fi

    if [[ -d "${LEGACY_STATE_DIR}" ]]; then
        cp -a "${LEGACY_STATE_DIR}/." "${STATE_DIR}/"
    fi

    MIGRATION_BACKUP_DIR="${STATE_DIR}/migration/legacy-runtime-$(date '+%Y%m%d_%H%M%S')"
    install -d -o root -g root -m 0700 "${MIGRATION_BACKUP_DIR}"
    [[ -f "${LEGACY_CONFIG_FILE}" ]] && cp -a "${LEGACY_CONFIG_FILE}" "${MIGRATION_BACKUP_DIR}/legacy.conf" || true
    [[ -f "${LEGACY_APP_DIR}/BUILD_INFO" ]] && cp -a "${LEGACY_APP_DIR}/BUILD_INFO" "${MIGRATION_BACKUP_DIR}/BUILD_INFO" || true
    [[ -f "${LEGACY_UNIT_FILE}" ]] && cp -a "${LEGACY_UNIT_FILE}" "${MIGRATION_BACKUP_DIR}/legacy.service" || true
    {
        printf 'legacy_service_active=%s\n' "${legacy_was_active}"
        printf 'legacy_service_enabled=%s\n' "${legacy_was_enabled}"
        printf 'migrated_to=%s\n' "${PRODUCT_ID}"
        printf 'source_ref=%s\n' "${SOURCE_REF}"
        printf 'source_commit=%s\n' "${SOURCE_SHA}"
    } >"${MIGRATION_BACKUP_DIR}/migration.txt"
fi

find "${APP_DIR}" \
    -mindepth 1 -maxdepth 1 \
    ! -name ".venv" \
    -exec rm -rf -- {} +
cp -a "${SOURCE_APP}/." "${APP_DIR}/"
chown -R root:root "${APP_DIR}"
chmod 0755 "${APP_DIR}/bin/digitalhouses-pve-agent-ups-policy-cmd"
chmod 0755 "${APP_DIR}/uninstall.sh"

if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
    python3 -m venv "${APP_DIR}/.venv"
elif ! "${APP_DIR}/.venv/bin/python" -m pip --version >/dev/null 2>&1; then
    echo "Повреждённый venv без pip обнаружен; пересоздаём."
    python3 -m venv --clear "${APP_DIR}/.venv"
fi

if ! "${APP_DIR}/.venv/bin/python" -m pip --version >/dev/null 2>&1; then
    echo "Ошибка: venv создан без pip."
    exit 1
fi

"${APP_DIR}/.venv/bin/python" -m pip install \
    --disable-pip-version-check \
    --upgrade pip
"${APP_DIR}/.venv/bin/python" -m pip install \
    --disable-pip-version-check \
    -r "${APP_DIR}/requirements.txt"

if [[ ! -f "${CONFIG_FILE}" ]]; then
    if [[ ! -r /dev/tty ]]; then
        echo "Первая установка требует терминал для ввода MQTT-параметров."
        exit 1
    fi

    while true; do
        mqtt_host=""
        mqtt_port="1883"
        mqtt_user=""
        mqtt_password=""
        confirm=""

        while [[ -z "${mqtt_host}" ]]; do
            printf "MQTT host: " >/dev/tty
            IFS= read -r mqtt_host </dev/tty
        done

        printf "MQTT port [1883]: " >/dev/tty
        IFS= read -r answer </dev/tty
        [[ -n "${answer}" ]] && mqtt_port="${answer}"

        if ! [[ "${mqtt_port}" =~ ^[0-9]+$ ]] \
            || ! (( mqtt_port >= 1 && mqtt_port <= 65535 )); then
            printf "Некорректный MQTT port. Допустимый диапазон: 1-65535.\n" >/dev/tty
            printf "Повторите ввод MQTT-параметров.\n\n" >/dev/tty
            continue
        fi

        printf "MQTT username [optional]: " >/dev/tty
        IFS= read -r mqtt_user </dev/tty

        printf "MQTT password [optional]: " >/dev/tty
        IFS= read -r -s mqtt_password </dev/tty
        printf "\n" >/dev/tty

        printf "\nПроверьте параметры:\n" >/dev/tty
        printf "  Host:     %s\n" "${mqtt_host}" >/dev/tty
        printf "  Port:     %s\n" "${mqtt_port}" >/dev/tty
        printf "  Username: %s\n" "${mqtt_user:-не задан}" >/dev/tty
        if [[ -n "${mqtt_password}" ]]; then
            printf "  Password: задан\n" >/dev/tty
        else
            printf "  Password: не задан\n" >/dev/tty
        fi

        printf "\nВсё верно? [y/N]: " >/dev/tty
        IFS= read -r confirm </dev/tty

        case "${confirm,,}" in
            y|yes)
                break
                ;;
            *)
                printf "Повторите ввод MQTT-параметров.\n\n" >/dev/tty
                ;;
        esac
    done

    previous_umask="$(umask)"
    umask 0077
    {
        printf '%s\n' "[general]"
        printf '%s\n' "instance_id ="
        printf '%s\n' "node_name = PVE"
        printf '%s\n' "log_level = info"
        printf '\n'
        printf '%s\n' "[mqtt]"
        printf 'host = %s\n' "${mqtt_host}"
        printf 'port = %s\n' "${mqtt_port}"
        printf 'username = %s\n' "${mqtt_user}"
        printf 'password = %s\n' "${mqtt_password}"
        printf '%s\n' "topic_prefix = ${CANONICAL_TOPIC_PREFIX}"
        printf '%s\n' "discovery_prefix = homeassistant"
        printf '%s\n' "keepalive_seconds = 60"
        printf '\n'
        printf '%s\n' "[telemetry]"
        printf '%s\n' "# Voluntary product telemetry. Default is OFF."
        printf '%s\n' "# Policy: https://github.com/DigitalHouses/home-assistant-apps/blob/main/docs/standards/PRODUCT_TELEMETRY_POLICY.md"
        printf '%s\n' "enabled = false"
        printf '\n'
        printf '%s\n' "[events]"
        printf '%s\n' "# PVE problem/recovery notification debounce. 0 disables debounce."
        printf '%s\n' "pve_problem_debounce_seconds = 30"
    } >"${CONFIG_FILE}"
    umask "${previous_umask}"
fi

chown root:root "${CONFIG_FILE}"
chmod 0600 "${CONFIG_FILE}"

if ! PYTHONPATH="${APP_DIR}" "${APP_DIR}/.venv/bin/python" -m app.main \
    --config "${CONFIG_FILE}" \
    --state-dir "${STATE_DIR}" \
    --check-config; then
    echo
    echo "Конфигурация DigitalHouses PVE Agent некорректна. Файл не был перезаписан."
    echo "Исправьте его командой:"
    echo "nano /etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf"
    exit 1
fi

"${APP_DIR}/.venv/bin/python" -m compileall -q "${APP_DIR}/app"

VERSION="$(tr -d '[:space:]' <"${APP_DIR}/VERSION")"
{
    printf 'version = %s\n' "${VERSION}"
    printf 'source = %s\n' "${SOURCE_REF}"
    printf 'commit = %s\n' "${SOURCE_SHA}"
} >"${APP_DIR}/BUILD_INFO"
chmod 0644 "${APP_DIR}/BUILD_INFO"

install -o root -g root -m 0644 \
    "${APP_DIR}/systemd/${SERVICE_NAME}" \
    "${UNIT_FILE}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" >/dev/null
systemctl restart "${SERVICE_NAME}"

if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "DigitalHouses PVE Agent не запустился."
    systemctl status "${SERVICE_NAME}" --no-pager || true
    journalctl -u "${SERVICE_NAME}" -n 80 --no-pager || true

    if [[ "${legacy_runtime_detected}" -eq 1 ]]; then
        echo "Canonical migration failed; восстанавливаю legacy runtime."
        systemctl stop "${SERVICE_NAME}" >/dev/null 2>&1 || true
        systemctl disable "${SERVICE_NAME}" >/dev/null 2>&1 || true
        rm -f -- "${UNIT_FILE}"
        rm -rf -- "${APP_DIR}" "${CONFIG_DIR}" "${STATE_DIR}"
        systemctl daemon-reload
        if [[ "${legacy_was_enabled}" -eq 1 ]]; then
            systemctl enable "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1 || true
        fi
        if [[ "${legacy_was_active}" -eq 1 ]]; then
            systemctl start "${LEGACY_SERVICE_NAME}" || true
        fi
    fi
    exit 1
fi

if [[ "${legacy_runtime_detected}" -eq 1 ]]; then
    if [[ -x "${LEGACY_APP_DIR}/.venv/bin/python" && -r "${LEGACY_CONFIG_FILE}" ]]; then
        PYTHONPATH="${LEGACY_APP_DIR}" "${LEGACY_APP_DIR}/.venv/bin/python" -m app.main \
            --config "${LEGACY_CONFIG_FILE}" \
            --state-dir "${LEGACY_STATE_DIR}" \
            --uninstall-mqtt-cleanup \
            || echo "WARNING: legacy MQTT cleanup не завершен; canonical runtime продолжит Discovery tombstones."
    fi

    systemctl disable "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1 || true
    rm -f -- "${LEGACY_UNIT_FILE}" "${LEGACY_ROOT_GUIDE}"
    rm -rf -- "${LEGACY_APP_DIR}" "${LEGACY_CONFIG_DIR}" "${LEGACY_STATE_DIR}"
    systemctl daemon-reload
    systemctl reset-failed "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1 || true
    echo "Legacy runtime удален после успешного запуска ${SERVICE_NAME}."
fi

{
    printf 'DIGITALHOUSES PVE AGENT — УСТАНОВЛЕННАЯ СБОРКА\n'
    printf '===================================\n'
    printf 'version = %s\n' "${VERSION}"
    printf 'source = %s\n' "${SOURCE_REF}"
    printf 'commit = %s\n' "${SOURCE_SHA}"
    printf '\n'
    cat "${APP_DIR}/digitalhouses_pve_agent.txt"
} >"${ROOT_GUIDE}"
chown root:root "${ROOT_GUIDE}"
chmod 0644 "${ROOT_GUIDE}"

echo
echo "DigitalHouses PVE Agent установлен."
echo "Версия: ${VERSION}"
echo "Source: ${SOURCE_REF}"
echo "Commit: ${SOURCE_SHA}"
echo "Config: ${CONFIG_FILE}"
echo "Status: systemctl status ${APP_NAME} --no-pager"
echo "Guide: ${ROOT_GUIDE}"
