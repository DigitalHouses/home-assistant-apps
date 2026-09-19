#!/usr/bin/env bash
set -Eeuo pipefail

PROFILE_NAME="DigitalHouses Beelink IT8613E"
IT87_RAW_BASE="https://raw.githubusercontent.com/frankcrawford/it87"
IT87_COMMIT="bc06d3488439e5fcd725c1bdcfcac994d6d95cac"
IT87_VERSION="v2.0-4-gbc06d34.20260913"

IT87_C_SHA="74e790fd9c437df1bee20ab7c5d92e7e186fd1d3"
COMPAT_H_SHA="d6485c20dae9135df6a79d009f5eca2422886461"
MAKEFILE_SHA="5b040b64ee1c7b421b87510b92f6da25bac4a5f3"
DKMS_CONF_SHA="bb6e28058ee35c438618fe167695db9f853469c2"

AUTOLOAD_FILE="/etc/modules-load.d/digitalhouses-beelink-it87.conf"
DKMS_SOURCE="/usr/src/it87-${IT87_VERSION}"
APP_ROOT="/opt/digitalhouses/dh_pve_app"

SUPPORTED_DMI_MARKERS=("AZW" "Beelink")

MODE="install"
case "${1:-}" in
    "")
        ;;
    --check)
        MODE="check"
        ;;
    -h|--help)
        echo "Usage: $0 [--check]"
        echo
        echo "Without arguments: install/repair the Beelink IT8613E host profile."
        echo "--check: read-only verification."
        exit 0
        ;;
    *)
        echo "Unknown argument: $1" >&2
        exit 2
        ;;
esac

log() {
    printf '%s\n' "$*"
}

die() {
    log "ERROR: $*"
    exit 1
}

read_trimmed() {
    local path="$1"
    if [[ -r "$path" ]]; then
        tr -d '\000' <"$path" | sed 's/[[:space:]]*$//'
    fi
}

git_blob_sha() {
    local path="$1"
    local size
    size="$(stat -c '%s' "$path")"
    { printf 'blob %s\0' "$size"; cat "$path"; } | sha1sum | awk '{print $1}'
}

dmi_supported() {
    local combined marker
    combined="${SYS_VENDOR} ${PRODUCT_NAME} ${BOARD_VENDOR} ${BOARD_NAME}"
    for marker in "${SUPPORTED_DMI_MARKERS[@]}"; do
        if [[ "${combined,,}" == *"${marker,,}"* ]]; then
            return 0
        fi
    done
    return 1
}

load_host_identity() {
    SYS_VENDOR="$(read_trimmed /sys/class/dmi/id/sys_vendor)"
    PRODUCT_NAME="$(read_trimmed /sys/class/dmi/id/product_name)"
    BOARD_VENDOR="$(read_trimmed /sys/class/dmi/id/board_vendor)"
    BOARD_NAME="$(read_trimmed /sys/class/dmi/id/board_name)"
    KERNEL="$(uname -r)"
}

validate_host() {
    [[ "${EUID}" -eq 0 ]] || die "run as root"
    command -v pveversion >/dev/null 2>&1 || die "this host is not Proxmox VE"
    load_host_identity

    log "profile=${PROFILE_NAME}"
    log "kernel=${KERNEL}"
    log "sys_vendor=${SYS_VENDOR:-unknown}"
    log "product_name=${PRODUCT_NAME:-unknown}"
    log "board_vendor=${BOARD_VENDOR:-unknown}"
    log "board_name=${BOARD_NAME:-unknown}"

    dmi_supported || die "unsupported DMI vendor/product; expected Beelink/AZW hardware"
}

dkms_status_text() {
    dkms status -m it87 -v "${IT87_VERSION}" 2>/dev/null || true
}

dkms_current_kernel_installed() {
    dkms_status_text         | grep -F "${KERNEL}"         | grep -q 'installed'
}

verify_module_resolution() {
    local module_path module_version

    module_path="$(modinfo -n it87 2>/dev/null || true)"
    module_version="$(modinfo -F version it87 2>/dev/null || true)"

    log "module_path=${module_path:-missing}"
    log "module_version=${module_version:-missing}"

    [[ "$module_path" == *"/updates/dkms/it87.ko"* ]]         || die "modprobe does not resolve to the DKMS it87 module"
    [[ "$module_version" == "${IT87_VERSION}" ]]         || die "resolved it87 version is not ${IT87_VERSION}"
}

verify_autoload() {
    [[ -r "${AUTOLOAD_FILE}" ]] || die "autoload file is missing"
    [[ "$(sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "${AUTOLOAD_FILE}")" == "it87" ]]         || die "autoload file is not canonical"
    log "autoload=${AUTOLOAD_FILE}"
}

verify_hwmon() {
    local h name found fan2 rpm
    found=0
    fan2=""

    for h in /sys/class/hwmon/hwmon*; do
        [[ -e "$h" ]] || continue
        name="$(cat "$h/name" 2>/dev/null || true)"
        if [ "$name" = "it8613" ]; then
            found=1
            log "hwmon=$h"
            log "hwmon_device=$(readlink -f "$h/device" 2>/dev/null || true)"
            fan2="$h/fan2_input"
            for input in "$h"/fan*_input; do
                [[ -r "$input" ]] || continue
                log "$(basename "$input")=$(cat "$input")"
            done
            break
        fi
    done

    [[ "$found" -eq 1 ]] || die "IT8613E hwmon device was not detected"
    [[ -r "$fan2" ]] || die "IT8613E fan2_input is missing"

    rpm="$(cat "$fan2")"
    [[ "$rpm" =~ ^[0-9]+$ ]] || die "fan2_input is not numeric"
}

verify_app_collector() {
    local python="${APP_ROOT}/.venv/bin/python"

    if [[ ! -x "$python" || ! -f "${APP_ROOT}/app/collectors/cooling.py" ]]; then
        log "dh_pve_app_collector=SKIP (App is not installed)"
        return 0
    fi

    PYTHONPATH="${APP_ROOT}" "$python" -c '
from pathlib import Path
from app.collectors.cooling import collect_fans

fans = collect_fans(Path("/sys/class/hwmon"))
for fan in fans:
    print(f"app_fan={fan.fan_id} rpm={fan.rpm} available={fan.available}")

if not any(fan.fan_id == "it8613_it87_2608_fan2" for fan in fans):
    raise SystemExit("expected it8613_it87_2608_fan2 was not found")
'
}

check_running_driver() {
    local running_version=""

    if [[ -r /sys/module/it87/version ]]; then
        running_version="$(cat /sys/module/it87/version)"
    fi

    if ! lsmod | awk '$1 == "it87" { found=1 } END { exit !found }'; then
        die "it87 is not loaded"
    fi

    log "running_version=${running_version:-unknown}"
    [[ "$running_version" == "${IT87_VERSION}" ]]         || die "loaded it87 is not the pinned DigitalHouses build"
}

run_check() {
    validate_host

    command -v dkms >/dev/null 2>&1 || die "dkms is not installed"
    [[ -e "/lib/modules/${KERNEL}/build/Makefile" ]]         || die "headers for the running kernel are missing"

    dkms_status_text
    dkms_current_kernel_installed         || die "it87 ${IT87_VERSION} is not installed by DKMS for ${KERNEL}"

    verify_module_resolution
    verify_autoload
    check_running_driver
    verify_hwmon
    verify_app_collector

    log "CHECK=PASS"
}

install_packages() {
    log
    log "=== Packages ==="
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y         ca-certificates         curl         dkms         build-essential         proxmox-default-headers         "proxmox-headers-${KERNEL}"

    [[ -e "/lib/modules/${KERNEL}/build/Makefile" ]]         || die "headers for ${KERNEL} were not installed"
}

download_one() {
    local name="$1"
    local expected="$2"
    local destination="$3"
    local actual

    curl -fsSL --retry 3 --retry-delay 2         "${IT87_RAW_BASE}/${IT87_COMMIT}/${name}"         -o "$destination"

    actual="$(git_blob_sha "$destination")"
    log "${name}: blob=${actual}"
    [[ "$actual" == "$expected" ]]         || die "source verification failed for ${name}"
}

prepare_source() {
    local stage="$1"

    install -d -m 0755 "$stage"
    download_one "it87.c" "${IT87_C_SHA}" "$stage/it87.c"
    download_one "compat.h" "${COMPAT_H_SHA}" "$stage/compat.h"
    download_one "Makefile" "${MAKEFILE_SHA}" "$stage/Makefile"
    download_one "dkms.conf" "${DKMS_CONF_SHA}" "$stage/dkms.conf"

    sed -i "s/^PACKAGE_VERSION=.*/PACKAGE_VERSION=\\"${IT87_VERSION}\\"/" "$stage/dkms.conf"
    printf '%s\n' "${IT87_VERSION}" >"$stage/VERSION"

    grep -Fx 'PACKAGE_NAME="it87"' "$stage/dkms.conf" >/dev/null
    grep -Fx 'PACKAGE_VERSION="'"${IT87_VERSION}"'"' "$stage/dkms.conf" >/dev/null
    grep -Fx 'AUTOINSTALL="yes"' "$stage/dkms.conf" >/dev/null
}

install_dkms() {
    local stage="$1"
    local status

    rm -rf "${DKMS_SOURCE}"
    install -d -m 0755 "${DKMS_SOURCE}"
    install -m 0644 "$stage/it87.c" "${DKMS_SOURCE}/it87.c"
    install -m 0644 "$stage/compat.h" "${DKMS_SOURCE}/compat.h"
    install -m 0644 "$stage/Makefile" "${DKMS_SOURCE}/Makefile"
    install -m 0644 "$stage/dkms.conf" "${DKMS_SOURCE}/dkms.conf"
    install -m 0644 "$stage/VERSION" "${DKMS_SOURCE}/VERSION"

    printf 'profile=%s\\nupstream=%s\\ncommit=%s\\nversion=%s\\n' \
        "${PROFILE_NAME}" \
        "${IT87_RAW_BASE}" \
        "${IT87_COMMIT}" \
        "${IT87_VERSION}" \
        >"${DKMS_SOURCE}/DIGITALHOUSES_SOURCE"

    status="$(dkms_status_text)"
    if [[ -z "$status" ]]; then
        dkms add -m it87 -v "${IT87_VERSION}"
        status="$(dkms_status_text)"
    else
        log "DKMS source already registered"
    fi

    if dkms_current_kernel_installed; then
        log "it87 ${IT87_VERSION} already installed for ${KERNEL}"
    else
        if ! printf '%s\n' "$status"             | grep -F "${KERNEL}"             | grep -q 'built'; then
            dkms build -m it87 -v "${IT87_VERSION}" -k "${KERNEL}"
        fi
        dkms install -m it87 -v "${IT87_VERSION}" -k "${KERNEL}"
    fi

    depmod -a "${KERNEL}"
}

enable_autoload() {
    install -d -m 0755 /etc/modules-load.d
    printf '%s\n' 'it87' >"${AUTOLOAD_FILE}"
    chmod 0644 "${AUTOLOAD_FILE}"
}

activate_driver() {
    local running_version=""

    if lsmod | awk '$1 == "it87" { found=1 } END { exit !found }'; then
        if [[ -r /sys/module/it87/version ]]; then
            running_version="$(cat /sys/module/it87/version)"
        fi
        log "it87 already loaded: ${running_version:-version unavailable}"

        if [[ "$running_version" != "${IT87_VERSION}" ]]; then
            log "NOTICE: pinned DKMS driver is installed, but another it87 is currently loaded."
            log "NOTICE: reboot once to activate the pinned DKMS driver."
            return 2
        fi
        return 0
    fi

    modprobe it87
}

run_install() {
    local tmp stage activation_rc
    validate_host
    install_packages

    tmp="$(mktemp -d /tmp/dh-beelink-it87.XXXXXX)"
    trap 'rm -rf "$tmp"' EXIT
    stage="$tmp/source"

    log
    log "=== Pinned source ==="
    prepare_source "$stage"

    log
    log "=== DKMS ==="
    install_dkms "$stage"

    log
    log "=== Autoload ==="
    enable_autoload
    verify_module_resolution
    verify_autoload

    log
    log "=== Runtime ==="
    activation_rc=0
    activate_driver || activation_rc=$?

    if [[ "$activation_rc" -eq 2 ]]; then
        log
        log "INSTALL=PASS"
        log "REBOOT_REQUIRED=yes"
        return 0
    fi
    [[ "$activation_rc" -eq 0 ]] || die "failed to activate it87"

    sleep 2
    check_running_driver
    verify_hwmon
    verify_app_collector

    log
    log "INSTALL=PASS"
    log "REBOOT_REQUIRED=no"
}

if [[ "$MODE" == "check" ]]; then
    run_check
else
    run_install
fi
