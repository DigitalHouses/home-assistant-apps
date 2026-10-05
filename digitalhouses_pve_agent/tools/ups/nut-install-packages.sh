#!/usr/bin/env bash
set -euo pipefail

transport=""
do_update=1

usage() {
    cat <<'EOF'
Usage:
  nut-install-packages.sh --transport usb|snmp [--no-update]

Installs NUT packages only.
It does not write /etc/nut and does not invoke service start/restart commands.\nPackage post-install scripts may still initialize units according to Debian policy.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --transport) transport="${2:-}"; shift 2 ;;
        --no-update) do_update=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ "$transport" != "usb" && "$transport" != "snmp" ]]; then
    echo "ERROR: --transport must be usb or snmp" >&2
    usage >&2
    exit 2
fi
if [[ "$(id -u)" -ne 0 ]]; then echo "ERROR: run as root" >&2; exit 1; fi
if ! command -v apt-get >/dev/null 2>&1; then echo "ERROR: Debian/Proxmox apt is required" >&2; exit 1; fi

packages=(nut-server nut-client)
if [[ "$transport" == "snmp" ]]; then packages+=(nut-snmp); fi

echo "=== DigitalHouses PVE Agent · install NUT packages ==="
echo "Transport: $transport"
printf 'Packages:'; printf ' %s' "${packages[@]}"; printf '\n'
echo "This helper does not write NUT configuration or invoke service start/restart commands."\necho "Debian package post-install scripts may still initialize units according to package policy."

if [[ "$do_update" -eq 1 ]]; then apt-get update; fi
DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"

echo
echo "Packages installed."
echo "Next: detect the UPS, choose the driver, then generate a staged PRIMARY configuration."
echo "Guide: digitalhouses_pve_agent/docs/UPS_SHUTDOWN_SETUP.md"
echo "DONE"
