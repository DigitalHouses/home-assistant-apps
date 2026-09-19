#!/usr/bin/env bash
set -euo pipefail

APP_NAME="dh_pve_app"
SERVICE_NAME="${APP_NAME}.service"
REPO_URL="https://github.com/DigitalHouses/home-assistant-apps.git"
SOURCE_REF="${DIGITALHOUSES_SOURCE_REF:-main}"

APP_DIR="/opt/digitalhouses/${APP_NAME}"
CONFIG_DIR="/etc/${APP_NAME}"
CONFIG_FILE="${CONFIG_DIR}/${APP_NAME}.conf"
STATE_DIR="/var/lib/${APP_NAME}"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}"
ROOT_GUIDE="/root/dh_app_pve.txt"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Установщик должен быть запущен от root."
    echo "Пример: curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/${APP_NAME}/install.sh | sudo bash"
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

SOURCE_APP="${tmp_dir}/repo/${APP_NAME}"

if [[ ! -f "${SOURCE_APP}/VERSION" ]]; then
    echo "Ошибка: ${APP_NAME} не найден в source ref ${SOURCE_REF}."
    exit 1
fi

install -d -o root -g root -m 0755 /opt/digitalhouses
install -d -o root -g root -m 0755 "${APP_DIR}"
install -d -o root -g root -m 0750 "${CONFIG_DIR}"
install -d -o root -g root -m 0750 "${STATE_DIR}"

find "${APP_DIR}" \
    -mindepth 1 -maxdepth 1 \
    ! -name ".venv" \
    -exec rm -rf -- {} +
cp -a "${SOURCE_APP}/." "${APP_DIR}/"
chown -R root:root "${APP_DIR}"
chmod 0755 "${APP_DIR}/bin/dh-pve-ups-policy-cmd"
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
        printf '%s\n' "topic_prefix = DigitalHouses/Global/dh_pve_app"
        printf '%s\n' "discovery_prefix = homeassistant"
        printf '%s\n' "keepalive_seconds = 60"
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
    echo "Конфигурация DH PVE App некорректна. Файл не был перезаписан."
    echo "Исправьте его командой:"
    echo "nano /etc/dh_pve_app/dh_pve_app.conf"
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
    echo "DH PVE App не запустился."
    systemctl status "${SERVICE_NAME}" --no-pager || true
    journalctl -u "${SERVICE_NAME}" -n 80 --no-pager || true
    exit 1
fi

{
    printf 'DH PVE APP — УСТАНОВЛЕННАЯ СБОРКА\n'
    printf '===================================\n'
    printf 'version = %s\n' "${VERSION}"
    printf 'source = %s\n' "${SOURCE_REF}"
    printf 'commit = %s\n' "${SOURCE_SHA}"
    printf '\n'
    cat "${APP_DIR}/dh_app_pve.txt"
} >"${ROOT_GUIDE}"
chown root:root "${ROOT_GUIDE}"
chmod 0644 "${ROOT_GUIDE}"

echo
echo "DH PVE App установлен."
echo "Версия: ${VERSION}"
echo "Source: ${SOURCE_REF}"
echo "Commit: ${SOURCE_SHA}"
echo "Config: ${CONFIG_FILE}"
echo "Status: systemctl status ${APP_NAME} --no-pager"
echo "Guide: ${ROOT_GUIDE}"
