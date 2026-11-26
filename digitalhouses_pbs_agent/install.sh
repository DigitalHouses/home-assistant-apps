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
Usage: bash install.sh [--non-interactive] [--set key=value ...] [--mqtt-password-stdin]
By default installs the latest published stable GitHub Release, pinned to its tag.
Optional DIGITALHOUSES_SOURCE_REF=digitalhouses_pbs_agent-vX.Y.Z pins a specific version.
Native INI settings are identical to dh-pbs-agent set. MQTT password only by stdin.
TELEMETRY: [telemetry] enabled=true sends product, version and random installation ID.
Privacy: https://github.com/DigitalHouses/home-assistant-apps/blob/main/docs/standards/PRODUCT_TELEMETRY_POLICY.md
For an existing 0.1.0 installation, use --set telemetry_enabled=true explicitly.

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
# Production convenience: select the newest *published stable release*, never main.
# Resolve once and pin the exact immutable tag before downloading source.
if [[ -z "$TAG" ]]; then
  command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 required to resolve release" >&2; exit 1; }
  TAG="$(python3 - <<'PYRELEASE'
import json, re, urllib.request
url = "https://api.github.com/repos/DigitalHouses/home-assistant-apps/releases"
stable = []
for page in range(1, 11):
    req = urllib.request.Request(
        f"{url}?per_page=100&page={page}",
        headers={"User-Agent": "DigitalHouses-PBS-Agent", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        rows = json.load(response)
    if not isinstance(rows, list):
        raise SystemExit("ERROR: invalid GitHub Releases response")
    for row in rows:
        if not isinstance(row, dict) or row.get("draft") or row.get("prerelease") or not row.get("published_at"):
            continue
        tag = str(row.get("tag_name", ""))
        match = re.fullmatch(r"digitalhouses_pbs_agent-v(\d+)\.(\d+)\.(\d+)", tag)
        if match:
            stable.append((tuple(map(int, match.groups())), tag))
    if len(rows) < 100:
        break
if not stable:
    raise SystemExit("ERROR: no published PBS Agent stable release")
print(max(stable)[1])
PYRELEASE
)"
  echo "RELEASE $TAG"
fi
if [[ "$TAG" =~ ^digitalhouses_pbs_agent-v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
  EXPECTED="${TAG#digitalhouses_pbs_agent-v}"
elif [[ "${DIGITALHOUSES_ALLOW_NON_RELEASE_REF:-0}" == "1" && -n "$TAG" ]]; then
  echo "WARNING: installing untagged PBS Agent development source for HOME acceptance only."
  EXPECTED=""
else
  echo "ERROR: canonical immutable PBS Agent release tag required" >&2; exit 1
fi
for cmd in systemctl proxmox-backup-debug; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: missing $cmd" >&2; exit 1; }
done
need_packages=()
command -v git >/dev/null 2>&1 || need_packages+=(git)
command -v python3 >/dev/null 2>&1 || need_packages+=(python3 python3-venv)
if command -v python3 >/dev/null 2>&1 && ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  need_packages+=(python3-venv)
fi
if (( ${#need_packages[@]} > 0 )); then
  command -v apt-get >/dev/null 2>&1 || { echo "ERROR: apt-get unavailable" >&2; exit 1; }
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${need_packages[@]}"
fi
mkdir -p /opt/digitalhouses "$(dirname "$CONFIG")" "$STATE"
chmod 700 "$(dirname "$CONFIG")" "$STATE"
TMP="$(mktemp -d /opt/digitalhouses/.pbs-agent-install.XXXXXXXX)"
STAGE="$TMP/stage"
OLD="$TMP/old"
BACKUP_CONFIG="$TMP/existing.conf"
CANDIDATE="$TMP/candidate.conf"
MAIN_UNIT="/etc/systemd/system/$SERVICE"
CONTROL_UNIT="/etc/systemd/system/digitalhouses_pbs_agent-control.service"
CONTROL_RUNNER="/usr/local/libexec/digitalhouses-pbs-agent-control-runner"
CLI="/usr/local/bin/dh-pbs-agent"
ROOT_GUIDE="/root/dh-pbs-agent.txt"
# Restore all management artifacts as well as the running service on failure.
preserve_file() {
  local key="$1" file="$2"
  if [[ -f "$file" ]]; then cp -p "$file" "$TMP/$key.old"; fi
}
restore_file() {
  local key="$1" file="$2"
  if [[ -f "$TMP/$key.old" ]]; then cp -p "$TMP/$key.old" "$file"; else rm -f "$file"; fi
}
preserve_file main_unit "$MAIN_UNIT"
preserve_file control_unit "$CONTROL_UNIT"
preserve_file control_runner "$CONTROL_RUNNER"
preserve_file cli "$CLI"
preserve_file guide "$ROOT_GUIDE"
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
      restore_file main_unit "$MAIN_UNIT"
      restore_file control_unit "$CONTROL_UNIT"
      restore_file control_runner "$CONTROL_RUNNER"
      restore_file cli "$CLI"
      restore_file guide "$ROOT_GUIDE"
      systemctl daemon-reload || true
      if ((ACTIVE_BEFORE == 1)); then systemctl start "$SERVICE" || true; fi
    fi
    echo "ERROR: PBS Agent installation did not complete; source/config rolled back" >&2
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT
git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$TAG" "$REPO" "$TMP/repo"
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
datastores =
[telemetry]
enabled = true
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
  "$STAGE/.venv/bin/python" -c 'import sys; from pathlib import Path; from app.config import load_config; cfg=load_config(Path(sys.argv[1])); sys.exit(0 if cfg.telemetry_enabled else "ERROR: telemetry not accepted; run installer again with --set telemetry_enabled=true after reviewing the privacy policy (existing installation untouched)")' "$CANDIDATE"
)
if systemctl is-active --quiet "$SERVICE"; then ACTIVE_BEFORE=1; fi
if ((ACTIVE_BEFORE == 1)); then systemctl stop "$SERVICE"; fi
if [[ -d "$TARGET" ]]; then mv "$TARGET" "$OLD"; fi
mv "$STAGE" "$TARGET"
SWAPPED=1
install -m 600 "$CANDIDATE" "$CONFIG"
install -m 755 "$TARGET/bin/dh-pbs-agent" "$CLI"
install -d -m 755 /usr/local/libexec
install -m 755 "$TARGET/bin/digitalhouses-pbs-agent-control-runner" "$CONTROL_RUNNER"
install -m 644 "$TARGET/systemd/digitalhouses_pbs_agent-control.service" "$CONTROL_UNIT"
install -m 644 "$TARGET/systemd/digitalhouses_pbs_agent.service" "$MAIN_UNIT"
install -m 600 "$TARGET/dh-pbs-agent.txt" "$ROOT_GUIDE"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl start "$SERVICE"
systemctl is-active --quiet "$SERVICE" || { echo "ERROR: PBS Agent service failed startup" >&2; exit 1; }
COMPLETED=1
echo "INSTALLED $PRODUCT $ACTUAL ($TAG, $COMMIT)"
echo "SERVICE ACTIVE; use /usr/local/bin/dh-pbs-agent status"
