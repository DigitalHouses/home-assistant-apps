#!/usr/bin/env bash
# Provision a dedicated, unprivileged SSH account for Recorder App disk metrics.
# Run as root inside the Linux machine/container hosting PostgreSQL or MariaDB.
# This script does not change SSH daemon settings or database permissions.
#
# Usage:
#   bash create_storage_ssh_user.sh
#   bash create_storage_ssh_user.sh --reset-password

ACCOUNT="dh_recorder"

main() {
    if [[ "$#" -gt 1 ]] || [[ "$#" -eq 1 && "$1" != "--reset-password" ]]; then
        printf '%s\n' "Usage: bash create_storage_ssh_user.sh [--reset-password]" >&2
        return 2
    fi

    if [[ "$(id -u)" -ne 0 ]]; then
        printf '%s\n' "ERROR: Run as root on the database host/container." >&2
        return 1
    fi

    local command_name
    for command_name in useradd passwd runuser id df; do
        if ! command -v "$command_name" >/dev/null 2>&1; then
            printf 'ERROR: Required command is missing: %s\n' "$command_name" >&2
            return 1
        fi
    done

    printf '%s\n' "========== DH RECORDER · STORAGE SSH USER =========="

    local reset_password=false
    if [[ "$#" -eq 1 ]]; then
        reset_password=true
    fi

    local exists=false
    if id "$ACCOUNT" >/dev/null 2>&1; then
        exists=true
        printf 'User %s already exists; no account changes needed.\n' "$ACCOUNT"
    fi

    if [[ "$exists" == false || "$reset_password" == true ]]; then
        if [[ ! -t 0 ]]; then
            printf '%s\n' "ERROR: An interactive terminal is required to set the password." >&2
            return 1
        fi
    fi

    if [[ "$exists" == false ]]; then
        if ! useradd -m -U -s /bin/sh "$ACCOUNT"; then
            printf 'ERROR: Failed to create user %s.\n' "$ACCOUNT" >&2
            return 1
        fi
        printf 'Created unprivileged user %s (no sudo privileges).\n' "$ACCOUNT"
    fi

    if [[ "$exists" == false || "$reset_password" == true ]]; then
        printf 'Set the SSH password for %s (input is hidden):\n' "$ACCOUNT"
        if ! passwd "$ACCOUNT"; then
            printf '%s\n' "ERROR: Password setup failed. Account may exist, but login is not ready." >&2
            return 1
        fi
    else
        printf '%s\n' "Existing password unchanged; use --reset-password to set a new one."
    fi

    printf '%s\n' "=== Verify unprivileged disk visibility ==="
    if ! runuser -u "$ACCOUNT" -- df -h /; then
        printf '%s\n' "ERROR: Cannot read filesystem usage as the dedicated account." >&2
        return 1
    fi

    printf '\n%s\n' "========== DONE =========="
    printf 'Recorder App storage: source=ssh, username=%s, port=22\n' "$ACCOUNT"
    printf '%s\n' "Set SSH host to the database server IP and use the password entered above."
    printf '%s\n' "The SSH server must allow password authentication; this script does not change sshd."
}

main "$@"
