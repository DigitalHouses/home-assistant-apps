#!/usr/bin/env bash
set -Eeuo pipefail

APP="/opt/digitalhouses/digitalhouses-stats"
WEB_ROOT="/var/www/digitalhouses-stats"
NGINX_SITE="/etc/nginx/sites-available/digitalhouses-stats"
NGINX_LINK="/etc/nginx/sites-enabled/digitalhouses-stats"
DASHBOARD_SERVICE="/etc/systemd/system/digitalhouses-stats-dashboard-api.service"
LAN_IP="192.168.11.254"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root."
    exit 1
fi

if ! ip -4 addr show | grep -q " ${LAN_IP}/"; then
    echo "Expected LAN address ${LAN_IP} is not configured on this host."
    exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx

install -d -o root -g root -m 0755 "${WEB_ROOT}"
rm -rf "${WEB_ROOT:?}/"*
cp -a "${APP}/dashboard/." "${WEB_ROOT}/"
chown -R root:root "${WEB_ROOT}"

install -o root -g root -m 0644     "${APP}/deploy/digitalhouses-stats-dashboard-api.service"     "${DASHBOARD_SERVICE}"

install -o root -g root -m 0644     "${APP}/deploy/nginx-digitalhouses-stats.conf"     "${NGINX_SITE}"

ln -sfn "${NGINX_SITE}" "${NGINX_LINK}"
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable digitalhouses-stats-dashboard-api nginx >/dev/null
systemctl restart digitalhouses-stats-dashboard-api

dashboard_ready=0
for attempt in $(seq 1 20); do
    if curl -fsS http://127.0.0.1:8081/healthz >/dev/null 2>&1; then
        dashboard_ready=1
        break
    fi
    sleep 0.5
done

if [[ "${dashboard_ready}" -ne 1 ]]; then
    echo "Dashboard API failed to become ready."
    systemctl status digitalhouses-stats-dashboard-api --no-pager || true
    journalctl -u digitalhouses-stats-dashboard-api -n 80 --no-pager || true
    exit 1
fi

nginx -t
systemctl restart nginx

echo
echo "=== DASHBOARD API ==="
curl -fsS http://127.0.0.1:8081/healthz
echo

echo
echo "=== LAN DASHBOARD ==="
curl -fsS "http://${LAN_IP}/healthz"
echo

echo
echo "Dashboard: http://${LAN_IP}/"
