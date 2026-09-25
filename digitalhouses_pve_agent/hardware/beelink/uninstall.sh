#!/usr/bin/env bash
set -Eeuo pipefail

IT87_VERSION="v2.0-4-gbc06d34.20260913"
AUTOLOAD_FILE="/etc/modules-load.d/digitalhouses-beelink-it87.conf"
DKMS_SOURCE="/usr/src/it87-${IT87_VERSION}"

log() {
    printf '%s\n' "$*"
}

die() {
    log "ERROR: $*"
    exit 1
}

[[ "${EUID}" -eq 0 ]] || die "run as root"
command -v pveversion >/dev/null 2>&1 || die "this host is not Proxmox VE"

KERNEL="$(uname -r)"

log "========== DigitalHouses Beelink IT87 uninstall =========="
log "kernel=${KERNEL}"

log
log "=== Remove autoload ==="
if [[ -e "${AUTOLOAD_FILE}" ]]; then
    rm -f "${AUTOLOAD_FILE}"
    log "removed=${AUTOLOAD_FILE}"
else
    log "autoload already absent"
fi

log
log "=== Remove DigitalHouses DKMS version ==="
if dkms status -m it87 -v "${IT87_VERSION}" 2>/dev/null | grep -q .; then
    dkms remove -m it87 -v "${IT87_VERSION}" --all
else
    log "DKMS version already absent"
fi

rm -rf "/usr/src/it87-${IT87_VERSION}"
depmod -a "${KERNEL}"

log
log "=== Module resolution after uninstall ==="
modinfo -n it87 2>/dev/null || log "it87 is not available through modprobe"

if lsmod | awk '$1 == "it87" { found=1 } END { exit !found }'; then
    log
    log "NOTICE: the currently loaded it87 remains in memory until reboot."
    log "NOTICE: reboot to return fully to the stock Proxmox module state."
fi

log
log "UNINSTALL=PASS"
