#!/usr/bin/env bash
# Installs or updates Agent HQ on an Ubuntu server. Run as root from the folder holding the code:
#   bash /opt/agent-hq/deploy/cloud/install.sh
# Safe to run again after copying new code: it never touches data/, config/ or .env.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE=/etc/agent-hq.env
SERVICE=/etc/systemd/system/agent-hq.service

[ "$(id -u)" = 0 ] || { echo "Run this as root."; exit 1; }

echo "==> Installing Python, ffmpeg and the firewall"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip ffmpeg ufw git

id hq >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin hq
mkdir -p "$APP_DIR/data"
chown -R hq:hq "$APP_DIR"

echo "==> Installing Agent HQ's Python packages (a few minutes)"
sudo -u hq python3 -m venv "$APP_DIR/.venv"
sudo -u hq "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u hq "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
    if [ -z "${HQ_PASSWORD:-}" ]; then
        read -r -s -p "Choose a password for the dashboard: " HQ_PASSWORD </dev/tty; echo
    fi
    [ -n "$HQ_PASSWORD" ] || { echo "A password is required."; exit 1; }
    printf 'HQ_PASSWORD=%s\n' "$HQ_PASSWORD" > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    if [ -z "${HQ_TZ:-}" ]; then
        read -r -p "Your time zone for the Boss's daily report (like America/New_York, Enter to skip): " HQ_TZ </dev/tty || true
    fi
    [ -n "${HQ_TZ:-}" ] && timedatectl set-timezone "$HQ_TZ"
fi

echo "==> Setting Agent HQ to start automatically"
cat > "$SERVICE" <<UNIT
[Unit]
Description=Agent HQ
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=hq
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
Environment=HQ_SUPERVISED=1
Environment=HQ_AUTO_UPDATE=1
ExecStartPre=-$APP_DIR/.venv/bin/python -m hq update
ExecStart=$APP_DIR/.venv/bin/python -m hq serve --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable agent-hq >/dev/null
systemctl restart agent-hq

# Only devices on your Tailscale network can reach the server. The public internet sees nothing.
if ip link show tailscale0 >/dev/null 2>&1; then
    echo "==> Locking the server to your Tailscale devices"
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    ufw allow in on tailscale0 >/dev/null
    ufw allow 41641/udp >/dev/null
    ufw --force enable >/dev/null
else
    echo "!! Tailscale isn't running, so the firewall was left alone. Set up Tailscale, then run this again."
fi

sleep 3
if systemctl is-active --quiet agent-hq; then
    echo
    echo "Agent HQ is running. Open http://$(hostname):8000 on your Mac or PC."
else
    echo "Agent HQ didn't start. Recent log:"
    journalctl -u agent-hq -n 30 --no-pager
    exit 1
fi
