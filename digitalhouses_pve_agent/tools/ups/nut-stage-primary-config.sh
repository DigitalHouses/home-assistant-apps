#!/usr/bin/env bash
set -euo pipefail
umask 077

ups_name=""
driver=""
port=""
ondelay=""
output_dir="/root/digitalhouses-nut-stage"

usage() {
    cat <<'EOF'
Usage:
  nut-stage-primary-config.sh --ups-name NAME --driver DRIVER --port PORT \
    [--ondelay SECONDS] [--output-dir DIR]

Creates a commissioning-safe NUT PRIMARY configuration in a staging directory.
It NEVER writes /etc/nut and does not invoke NUT service start/restart actions.
The generated upsmon.conf intentionally uses SHUTDOWNCMD "/bin/true".
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ups-name) ups_name="${2:-}"; shift 2 ;;
        --driver) driver="${2:-}"; shift 2 ;;
        --port) port="${2:-}"; shift 2 ;;
        --ondelay) ondelay="${2:-}"; shift 2 ;;
        --output-dir) output_dir="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ "$(id -u)" -ne 0 ]]; then echo "ERROR: run as root" >&2; exit 1; fi
if [[ -z "$ups_name" || -z "$driver" || -z "$port" ]]; then
    echo "ERROR: --ups-name, --driver and --port are required" >&2
    usage >&2
    exit 2
fi
if [[ ! "$ups_name" =~ ^[A-Za-z0-9_.-]+$ ]]; then echo "ERROR: unsafe UPS name" >&2; exit 2; fi
if [[ ! "$driver" =~ ^[A-Za-z0-9_.-]+$ ]]; then echo "ERROR: unsafe driver name" >&2; exit 2; fi
if [[ ! "$port" =~ ^[A-Za-z0-9._:/%+@-]+$ ]]; then echo "ERROR: unsafe port value" >&2; exit 2; fi
if [[ -n "$ondelay" && ! "$ondelay" =~ ^[0-9]+$ ]]; then echo "ERROR: --ondelay must be a non-negative integer" >&2; exit 2; fi
if ! command -v realpath >/dev/null 2>&1; then
    echo "ERROR: realpath is required to validate the staging path" >&2
    exit 1
fi
output_dir="$(realpath -m -- "$output_dir")"
if [[ "$output_dir" != /root/* ]]; then
    echo "ERROR: --output-dir must be a private staging directory below /root" >&2
    exit 2
fi
if ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: openssl is required to generate the local PRIMARY service credential" >&2
    exit 1
fi

# Generate a service credential instead of accepting it on the command line.
# The secret is written only to the private staging files and is never printed.
password="$(openssl rand -hex 24)"

if [[ -e "$output_dir" ]]; then
    if [[ ! -d "$output_dir" || -L "$output_dir" ]]; then
        echo "ERROR: staging path must be a real directory" >&2
        exit 2
    fi
    if find "$output_dir" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
        echo "ERROR: staging directory must be empty: $output_dir" >&2
        exit 2
    fi
else
    mkdir -m 0700 "$output_dir"
fi
chmod 0700 "$output_dir"

cat >"$output_dir/nut.conf" <<'EOF'
MODE=standalone
EOF

{
    printf '[%s]\n' "$ups_name"
    printf '    driver = %s\n' "$driver"
    printf '    port = %s\n' "$port"
    if [[ -n "$ondelay" ]]; then
        printf '    ondelay = %s\n' "$ondelay"
    else
        printf '    # ondelay = <driver-supported restore delay; configure after verification>\n'
    fi
    printf '    # Add only driver-specific options verified for this UPS model.\n'
} >"$output_dir/ups.conf"

cat >"$output_dir/upsd.conf" <<'EOF'
LISTEN 127.0.0.1 3493
EOF

cat >"$output_dir/upsd.users" <<EOF
[dh_primary_user]
    password = $password
    upsmon primary
    instcmds = ALL
EOF

cat >"$output_dir/upsmon.conf" <<EOF
MONITOR $ups_name@127.0.0.1 1 dh_primary_user $password primary
MINSUPPLIES 1
POLLFREQ 5
POLLFREQALERT 5
DEADTIME 15
NOCOMMWARNTIME 300
HOSTSYNC 120
FINALDELAY 5
SHUTDOWNCMD "/bin/true"
EOF

cat >"$output_dir/digitalhouses_pve_agent-ups.ini" <<EOF
[ups]
enabled = true
name = $ups_name
host = 127.0.0.1
port = 3493
command_username = dh_primary_user
command_password = $password
EOF

chmod 0600 "$output_dir"/*
unset password

echo "=== DigitalHouses PVE Agent · NUT PRIMARY staging complete ==="
echo "Output: $output_dir"
echo "Nothing was written to /etc/nut; this helper did not invoke any service start/restart action."
echo 'SHUTDOWNCMD is "/bin/true" intentionally until final reviewed activation.'
echo "Configure a supported ondelay before expecting power-restore readiness."
echo "Guide: digitalhouses_pve_agent/docs/UPS_SHUTDOWN_SETUP.md"
echo "DONE"
