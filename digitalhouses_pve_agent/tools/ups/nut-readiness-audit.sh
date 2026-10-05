#!/usr/bin/env bash
set -u
set -o pipefail

echo "=== DigitalHouses PVE Agent · UPS/NUT readiness audit ==="
echo "Mode: READ-ONLY"

section() { printf '\n=== %s ===\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

section "Host"
if have pveversion; then pveversion || true; else echo "PVE: pveversion not found"; fi
uname -a || true

section "Installed NUT packages"
if have dpkg-query; then
    dpkg-query -W -f='${binary:Package}\t${Version}\t${db:Status-Abbrev}\n' 'nut*' 2>/dev/null \
        | awk '$3 ~ /^ii/ {print}' || true
else
    echo "dpkg-query not available"
fi

section "NUT mode"
if [[ -r /etc/nut/nut.conf ]]; then
    awk '/^[[:space:]]*#/ {next} /^[[:space:]]*MODE[[:space:]]*=/ {print}' /etc/nut/nut.conf || true
else
    echo "/etc/nut/nut.conf: not readable"
fi

section "Configured UPS names"
if [[ -r /etc/nut/ups.conf ]]; then
    awk '/^[[:space:]]*\[[^]]+\][[:space:]]*(#.*)?$/ {
        line=$0; sub(/^[[:space:]]*\[/, "", line); sub(/\][[:space:]]*(#.*)?$/, "", line); print line
    }' /etc/nut/ups.conf || true
else
    echo "/etc/nut/ups.conf: not readable"
fi

section "USB discovery"
if have nut-scanner; then timeout 15s nut-scanner -U 2>&1 || true; else echo "nut-scanner not installed"; fi

section "NUT services"
if have systemctl; then
    for unit in nut-driver.target nut-server.service nut-monitor.service; do
        state="$(systemctl is-active "$unit" 2>/dev/null || true)"
        enabled="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
        printf '%-24s active=%-12s enabled=%s\n' "$unit" "${state:-unknown}" "${enabled:-unknown}"
    done
else
    echo "systemctl not available"
fi

section "Local upsd inventory"
if have upsc; then upsc -l 127.0.0.1 2>&1 || true; else echo "upsc not installed"; fi

section "upsmon PRIMARY role (password-safe)"
if [[ -r /etc/nut/upsmon.conf ]]; then
    awk '
      /^[[:space:]]*#/ {next}
      toupper($1) == "MONITOR" {printf "MONITOR target=%s role=%s\n", $2, $6}
      toupper($1) == "SHUTDOWNCMD" {line=$0; sub(/^[[:space:]]*SHUTDOWNCMD[[:space:]]+/, "", line); printf "SHUTDOWNCMD=%s\n", line}
      toupper($1) == "HOSTSYNC" {printf "HOSTSYNC=%s\n", $2}
      toupper($1) == "FINALDELAY" {printf "FINALDELAY=%s\n", $2}
    ' /etc/nut/upsmon.conf || true
else
    echo "/etc/nut/upsmon.conf: not readable"
fi

section "Configured restore delay"
if [[ -r /etc/nut/ups.conf ]]; then
    awk '/^[[:space:]]*#/ {next} /^[[:space:]]*ondelay[[:space:]]*=/ {
        line=$0; sub(/^[[:space:]]*/, "", line); print line
    }' /etc/nut/ups.conf || true
fi

section "DigitalHouses PVE Agent preflight (optional)"
APP=/opt/digitalhouses/digitalhouses_pve_agent
CFG=/etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf
STATE=/var/lib/digitalhouses_pve_agent
if [[ -x "$APP/.venv/bin/python" && -r "$CFG" ]]; then
    PYTHONPATH="$APP" "$APP/.venv/bin/python" -m app.main \
        --config "$CFG" --state-dir "$STATE" --ups-policy-preflight || true
else
    echo "DigitalHouses PVE Agent is not installed/configured; Agent preflight skipped."
    echo "Host/NUT/UPS audit above is still valid."
fi

echo
echo "=== DONE · READ-ONLY ==="
