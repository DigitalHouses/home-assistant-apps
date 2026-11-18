#!/usr/bin/env bash
# Install from a canonical immutable PBS Agent GitHub Release tag only.
set -euo pipefail
PRODUCT=digitalhouses_pbs_agent
SERVICE="${PRODUCT}.service"
REPO="https://github.com/DigitalHouses/home-assistant-apps.git"
TARGET="/opt/digitalhouses/${PRODUCT}"
CONFIG="/etc/${PRODUCT}/${PRODUCT}.conf"
STATE="/var/lib/${PRODUCT}"
TAG="${DIGITALHOUSES_SOURCE_REF:-}"
declare -a CHANGES=()
usage() {
  cat <<'EOF'
Usage: DIGITALHOUSES_SOURCE_REF=digitalhouses_pbs_agent-vX.Y.Z bash install.sh [--non-interactive] [--set key=value] [--mqtt-password-stdin]
Native INI settings are identical to dh-pbs-agent set. MQTT password only by stdin.
EOF
}
while (($#)); do
  case "$1" in
    --non-interactive) shift ;;
    --set) [[ $# -ge 2 ]] || { usage; exit 2; }; CHANGES+=(--set "$2"); shift 2 ;;
    --mqtt-password-stdin) CHANGES+=(--set "mqtt_password=-"); shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: invalid installer option" >&2; exit 2 ;;
  esac
done
[[ "$(id -u)" -eq 0 ]] || { echo "ERROR: root required" >&2; exit 1; }
if [[ "$TAG" =~ ^digitalhouses_pbs_agent-v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
  EXPECTED="${TAG#digitalhouses_pbs_agent-v}"
elif [[ "${DIGITALHOUSES_ALLOW_NON_RELEASE_REF:-0}" == "1" && -n "$TAG" ]]; then
  echo "WARNING: installing untagged PBS Agent development source for HOME acceptance only."
  EXPECTED=""
else
  echo "ERROR: canonical immutable PBS Agent release tag required" >&2; exit 1
fi
for cmd in git python3 systemctl; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: missing $cmd" >&2; exit 1; }
done
mkdir -p /opt/digitalhouses "$(dirname "$CONFIG")" "$STATE"
chmod 700 "$(dirname "$CONFIG")" "$STATE"
TMP="$(mktemp -d /opt/digitalhouses/.pbs-agent-install.XXXXXXXX)"
STAGE="$TMP/stage"
OLD="$TMP/old"
BACKUP_CONFIG="$TMP/existing.conf"
CANDIDATE="$TMP/candidate.conf"
ACTIVE_BEFORE=0
SWAPPED=0
COMPLETED=0
cleanup() {
  if ((COMPLETED == 0)); then
    if ((SWAPPED == 1)); then
      systemctl stop "$SERVICE" >/dev/null 2>&1 || true
      rm -rf "$TARGET"
      if [[ -d "$OLD" ]]; then mv "$OLD" "$TARGET"; fi
      if [[ -f "$BACKUP_CONFIG" ]]; then
        install -m 600 "$BACKUP_CONFIG" "$CONFIG"
      else
        rm -f "$CONFIG"
      fi
      systemctl daemon-reload || true
      if ((ACTIVE_BEFORE == 1)); then systemctl start "$SERVICE" || true; fi
    fi
    echo "ERROR: PBS Agent installation did not complete; source/config rolled back" >&2
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT
git clone --quiet --depth 1 --branch "$TAG" "$REPO" "$TMP/repo"
ACTUAL="$(cat "$TMP/repo/$PRODUCT/VERSION")"
[[ -z "$EXPECTED" || "$ACTUAL" == "$EXPECTED" ]] || { echo "ERROR: VERSION does not match release tag" >&2; exit 1; }
COMMIT="$(git -C "$TMP/repo" rev-parse HEAD)"
mkdir -p "$STAGE"
cp -a "$TMP/repo/$PRODUCT/." "$STAGE/"
python3 -m venv "$STAGE/.venv"
"$STAGE/.venv/bin/python" -m pip install -q -r "$STAGE/requirements.txt"
printf 'version=%s\nsource=%s\ncommit=%s\n' "$ACTUAL" "$TAG" "$COMMIT" > "$STAGE/BUILD_INFO"
if [[ -e "$CONFIG" ]]; then
  cp -p "$CONFIG" "$CANDIDATE"
  cp -p "$CONFIG" "$BACKUP_CONFIG"
else
  cat > "$CANDIDATE" <<'EOF'
[general]
log_level = info
[mqtt]
host =
port = 1883
username =
password =
[pbs]
url = https://127.0.0.1:8007
token_id =
token_secret_file = /etc/digitalhouses_pbs_agent/pbs.token
insecure_localhost = true
datastores =
[monitor]
poll_seconds = 300
backup_rules =
sync_rules =
warning_percent = 80
critical_percent = 90
EOF
fi
chmod 600 "$CANDIDATE"
(
  cd "$STAGE"
  export PYTHONPATH="$STAGE"
  "$STAGE/.venv/bin/python" -m app.installer "$CANDIDATE" "${CHANGES[@]}"
  "$STAGE/.venv/bin/python" -m app.main --config "$CANDIDATE" --check-config
)
if systemctl is-active --quiet "$SERVICE"; then ACTIVE_BEFORE=1; fi
if ((ACTIVE_BEFORE == 1)); then systemctl stop "$SERVICE"; fi
if [[ -d "$TARGET" ]]; then mv "$TARGET" "$OLD"; fi
mv "$STAGE" "$TARGET"
SWAPPED=1
install -m 600 "$CANDIDATE" "$CONFIG"
install -m 755 "$TARGET/bin/dh-pbs-agent" /usr/local/bin/dh-pbs-agent
install -m 644 "$TARGET/systemd/digitalhouses_pbs_agent.service" "/etc/systemd/system/$SERVICE"
install -m 600 "$TARGET/dh-pbs-agent.txt" /root/dh-pbs-agent.txt
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl start "$SERVICE"
systemctl is-active --quiet "$SERVICE" || { echo "ERROR: PBS Agent service failed startup" >&2; exit 1; }
COMPLETED=1
echo "INSTALLED $PRODUCT $ACTUAL ($TAG, $COMMIT)"
echo "SERVICE ACTIVE; use /usr/local/bin/dh-pbs-agent status"
