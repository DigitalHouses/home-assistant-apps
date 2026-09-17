#!/usr/bin/env bash
set -euo pipefail

APP_NAME="dh_pve_app"
SERVICE_NAME="${APP_NAME}.service"
APP_DIR="/opt/digitalhouses/${APP_NAME}"
CONFIG_DIR="/etc/${APP_NAME}"
CONFIG_FILE="${CONFIG_DIR}/${APP_NAME}.conf"
STATE_DIR="/var/lib/${APP_NAME}"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}"

purge=0
if [[ "$#" -gt 1 ]]; then
    echo "Неизвестный аргумент. Использование: $0 [--purge]"
    exit 2
fi
if [[ "$#" -eq 1 ]]; then
    if [[ "$1" != "--purge" ]]; then
        echo "Неизвестный аргумент: $1"
        echo "Использование: $0 [--purge]"
        exit 2
    fi
    purge=1
fi

if [[ "${EUID}" -ne 0 ]]; then
    echo "Удаление должно быть запущено от root."
    exit 1
fi

if ! command -v pveversion >/dev/null 2>&1 || [[ ! -d /etc/pve ]]; then
    echo "Ошибка: этот uninstall предназначен для Proxmox VE."
    exit 1
fi

if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
    echo "Ошибка: установленный Python runtime dh_pve_app не найден."
    echo "Локальная установка не изменена."
    exit 1
fi

if [[ ! -r "${CONFIG_FILE}" ]]; then
    echo "Ошибка: конфигурация MQTT недоступна: ${CONFIG_FILE}"
    echo "Локальная установка не изменена."
    exit 1
fi

was_active=0
was_enabled=0
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    was_active=1
fi
if systemctl is-enabled --quiet "${SERVICE_NAME}"; then
    was_enabled=1
fi
echo "До удаления: active=${was_active}, enabled=${was_enabled}"

if systemctl cat "${SERVICE_NAME}" >/dev/null 2>&1; then
    if ! systemctl stop "${SERVICE_NAME}"; then
        echo "Ошибка: не удалось остановить ${SERVICE_NAME}."
        echo "Локальная установка не изменена."
        exit 1
    fi
fi

if ! PYTHONPATH="${APP_DIR}" "${APP_DIR}/.venv/bin/python" -m app.main \
    --config "${CONFIG_FILE}" \
    --state-dir "${STATE_DIR}" \
    --uninstall-mqtt-cleanup; then
    echo "MQTT cleanup не завершен. Локальная установка сохранена."
    if [[ "${was_active}" -eq 1 ]]; then
        echo "Восстанавливаю ранее запущенный ${SERVICE_NAME}."
        if ! systemctl start "${SERVICE_NAME}"; then
            echo "Ошибка: ${SERVICE_NAME} не удалось запустить обратно."
        fi
    fi
    exit 1
fi

if [[ "${was_enabled}" -eq 1 ]]; then
    if ! systemctl disable "${SERVICE_NAME}" >/dev/null 2>&1; then
        echo "Ошибка: не удалось отключить автозапуск ${SERVICE_NAME}."
        echo "Локальная установка сохранена."
        if [[ "${was_active}" -eq 1 ]]; then
            echo "Восстанавливаю ранее запущенный ${SERVICE_NAME}."
            systemctl start "${SERVICE_NAME}" || true
        fi
        exit 1
    fi
else
    systemctl disable "${SERVICE_NAME}" >/dev/null 2>&1 || true
fi

rm -f -- "${UNIT_FILE}"
rm -rf -- "${APP_DIR}"

if [[ "${purge}" -eq 1 ]]; then
    echo "Полное удаление: удаляю config/state."
    rm -rf -- "${CONFIG_DIR}" "${STATE_DIR}"
else
    echo "Config/state сохранены:"
    echo "  ${CONFIG_DIR}/"
    echo "  ${STATE_DIR}/"
fi

systemctl daemon-reload
systemctl reset-failed "${SERVICE_NAME}" >/dev/null 2>&1 || true

echo "DH PVE App удален."
