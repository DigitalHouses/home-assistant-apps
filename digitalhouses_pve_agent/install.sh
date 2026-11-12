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
CLI_GUIDE="/root/dh-pve-agent.txt"
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

# Values stay in the native INI. Password flags add stdin sentinels, never
# password contents to argv. Both secrets are read in flag/--set order.
NON_INTERACTIVE=0
CONFIG_SETTINGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --non-interactive) NON_INTERACTIVE=1; shift ;;
        --set)
            if [[ $# -lt 2 ]]; then echo "ERROR: --set requires key=value" >&2; exit 2; fi
            CONFIG_SETTINGS+=("$2"); shift 2 ;;
        --mqtt-password-stdin) CONFIG_SETTINGS+=("mqtt_password=-"); shift ;;
        --ups-command-password-stdin) CONFIG_SETTINGS+=("ups_command_password=-"); shift ;;
        --help|-h)
            echo 'Usage: install.sh [--non-interactive] [--set key=value ...] [--mqtt-password-stdin] [--ups-command-password-stdin]'
            echo 'Secrets: one stdin line per password flag, in argument order. Native INI keys/aliases: /usr/local/bin/dh-pve-agent help'
            exit 0 ;;
        *) echo "ERROR: unknown installer argument" >&2; exit 2 ;;
    esac
done

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
for command_name in git curl tar python3 smartctl ipmitool lspci dmidecode; do
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
        ipmitool \
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

# Preflight before replacing the installed app, native config or services.
PREPARED_CONFIG="${tmp_dir}/native.conf"
CONFIG_BASE_SHA="-"
if [[ -f "${CONFIG_FILE}" ]]; then
    CONFIG_BASE_SHA="$(sha256sum "${CONFIG_FILE}" | cut -d ' ' -f1)"
    cp -p "${CONFIG_FILE}" "${PREPARED_CONFIG}"
elif [[ -f "${LEGACY_CONFIG_FILE}" ]]; then
    cp -p "${LEGACY_CONFIG_FILE}" "${PREPARED_CONFIG}"
    sed -i -E \
        "s|^([[:space:]]*topic_prefix[[:space:]]*=[[:space:]]*)${LEGACY_TOPIC_PREFIX}([[:space:]]*)$|\\1${CANONICAL_TOPIC_PREFIX}\\2|" \
        "${PREPARED_CONFIG}"
else
    (umask 0077; printf '[general]\ninstance_id =\nnode_name = PVE\nlog_level = info\n\n[mqtt]\nhost =\n' >"${PREPARED_CONFIG}")
fi
PREPARE_FLAGS=()
[[ "${NON_INTERACTIVE}" -eq 1 ]] && PREPARE_FLAGS+=(--non-interactive)
PYTHONPATH="${SOURCE_APP}" python3 -m app.install_config \
    "${PREPARED_CONFIG}" "${PREPARE_FLAGS[@]}" "${CONFIG_SETTINGS[@]}"

if [[ -f "${CONFIG_FILE}" ]]; then
    PYTHONPATH="${SOURCE_APP}" python3 -c \
        'import sys; from pathlib import Path; from app.config import load_config; from app.restart_safety import guard_restart; guard_restart(load_config(Path(sys.argv[1])), state_dir=Path(sys.argv[2]))' \
        "${CONFIG_FILE}" "${STATE_DIR}"
elif [[ -f "${LEGACY_CONFIG_FILE}" ]]; then
    PYTHONPATH="${SOURCE_APP}" python3 -c \
        'import sys; from pathlib import Path; from app.config import load_config; from app.restart_safety import guard_restart; guard_restart(load_config(Path(sys.argv[1])), state_dir=Path(sys.argv[2]))' \
        "${LEGACY_CONFIG_FILE}" "${LEGACY_STATE_DIR}"
fi

legacy_runtime_detected=0
legacy_was_active=0
legacy_was_enabled=0
if systemctl cat "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1 \
    || [[ -d "${LEGACY_APP_DIR}" || -f "${LEGACY_CONFIG_FILE}" || -d "${LEGACY_STATE_DIR}" ]]; then
    legacy_runtime_detected=1
    if [[ ! -r "${LEGACY_CONFIG_FILE}" ]]; then
        echo "Ошибка: legacy runtime обнаружен, но конфигурация недоступна: ${LEGACY_CONFIG_FILE}"
        echo "MQTT namespace нельзя безопасно очистить без исходной конфигурации."
        exit 1
    fi
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

PYTHONPATH="${APP_DIR}" "${APP_DIR}/.venv/bin/python" -m app.install_config \
    --commit "${PREPARED_CONFIG}" "${CONFIG_FILE}" "${CONFIG_BASE_SHA}"

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

if [[ "${legacy_runtime_detected}" -eq 1 ]]; then
    echo "Очистка retained MQTT legacy namespace перед canonical startup."
    if ! PYTHONPATH="${APP_DIR}" "${APP_DIR}/.venv/bin/python" -m app.main \
        --config "${LEGACY_CONFIG_FILE}" \
        --state-dir "${LEGACY_STATE_DIR}" \
        --migration-mqtt-cleanup; then
        echo "Ошибка: retained MQTT legacy namespace не очищен."
        echo "Canonical runtime не запускается; восстанавливаю legacy service."
        rm -rf -- "${APP_DIR}" "${CONFIG_DIR}" "${STATE_DIR}"
        if [[ "${legacy_was_enabled}" -eq 1 ]]; then
            systemctl enable "${LEGACY_SERVICE_NAME}" >/dev/null 2>&1 || true
        fi
        if [[ "${legacy_was_active}" -eq 1 ]]; then
            systemctl start "${LEGACY_SERVICE_NAME}" || true
        fi
        exit 1
    fi
fi

install -d -o root -g root -m 0755 /usr/local/bin
install -o root -g root -m 0750 "${APP_DIR}/bin/dh-pve-agent" /usr/local/bin/dh-pve-agent
install -o root -g root -m 0600 "${APP_DIR}/dh-pve-agent.txt" "${CLI_GUIDE}"

install -d -o root -g root -m 0755 /usr/local/libexec
install -o root -g root -m 0755 \
    "${APP_DIR}/bin/digitalhouses-pve-agent-update-runner" \
    /usr/local/libexec/digitalhouses-pve-agent-update-runner
install -o root -g root -m 0644 \
    "${APP_DIR}/systemd/digitalhouses_pve_agent-update.service" \
    /etc/systemd/system/digitalhouses_pve_agent-update.service
install -o root -g root -m 0644 \
    "${APP_DIR}/systemd/digitalhouses_pve_agent-update-recover.service" \
    /etc/systemd/system/digitalhouses_pve_agent-update-recover.service

install -o root -g root -m 0644 \
    "${APP_DIR}/systemd/${SERVICE_NAME}" \
    "${UNIT_FILE}"

PYTHONPATH="${APP_DIR}" "${APP_DIR}/.venv/bin/python" -c \
    'from app.config import load_config; from app.restart_safety import guard_restart; from app.main import DEFAULT_CONFIG; guard_restart(load_config(DEFAULT_CONFIG))'
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
chmod 0600 "${ROOT_GUIDE}"

echo
echo "DigitalHouses PVE Agent установлен."
echo "Версия: ${VERSION}"
echo "Source: ${SOURCE_REF}"
echo "Commit: ${SOURCE_SHA}"
echo "Config: ${CONFIG_FILE}"
echo "Status: systemctl status ${APP_NAME} --no-pager"
echo "Guide: ${ROOT_GUIDE}"
