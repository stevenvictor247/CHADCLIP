#!/usr/bin/env bash
# Installs (or repairs, or updates) Agent HQ on an Ubuntu 24.04 cloud server (Oracle Always Free, Vultr, any other). Safe to run again at any time: it never
# touches data/, config/ or your settings.
#
# Normally you never run this yourself. HQ's Move page makes a "setup text" that you paste into the cloud provider's
# Cloud-Init User-Data box; it downloads HQ to /opt/agent-hq and runs this with:
#   HQ_PASSWORD  a one-time password for the new server (your own replaces it when your HQ moves in)
#   HQ_TZ        your time zone, like America/Detroit
#   TS_AUTHKEY   a Tailscale auth key, so the server joins your Tailscale network by itself
#   HQ_WAITING=1 a brand-new server starts on standby, waiting for your HQ to move in (it can't post before that)
# By hand, as root: bash /opt/agent-hq/deploy/cloud/install.sh
#
# What you get: HQ starts at boot and restarts if it crashes; it updates itself (only to versions that passed every
# test, never in the middle of a post) and goes back to the last good version if an update won't start; a watchdog
# checks it every 5 minutes and texts you if something's wrong; security updates install themselves; only your
# Tailscale devices can reach the server; and Arial Black is installed so captions look exactly as they do on the PC.
set -euo pipefail
umask 022

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE=/etc/agent-hq.env
HQ_HOME=/var/lib/agent-hq
VENV="$APP_DIR/.venv"
UNITS=/etc/systemd/system

[ "$(id -u)" = 0 ] || { echo "Run this as root."; exit 1; }
export DEBIAN_FRONTEND=noninteractive
say() { echo; echo "==> $*"; }

say "Installing Python, ffmpeg, git, fonts and the firewall"
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip ffmpeg git ufw sqlite3 fontconfig curl unattended-upgrades
# Chad's captions use Arial Black, like on Windows. Microsoft's free core fonts package has it.
echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections
apt-get install -y -q ttf-mscorefonts-installer || echo "!! Couldn't install Arial Black; captions will use a similar font."
fc-cache -f >/dev/null 2>&1 || true

say "Turning on automatic security updates"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
cat > /etc/apt/apt.conf.d/52agent-hq-reboot <<'CONF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
CONF

if ! systemd-detect-virt --container -q 2>/dev/null && ! swapon --show | grep -q .; then
    say "Adding 4 GB of swap, so a big video job can't run the server out of memory"
    fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if [ -n "${HQ_TZ:-}" ]; then
    timedatectl set-timezone "$HQ_TZ" 2>/dev/null || echo "!! Unknown time zone $HQ_TZ, left as it was."
fi

say "Setting up the hq user"
if id hq >/dev/null 2>&1; then
    usermod -d "$HQ_HOME" hq
else
    useradd --system --home-dir "$HQ_HOME" --shell /usr/sbin/nologin hq
fi
mkdir -p "$HQ_HOME" "$APP_DIR/data"
chown -R hq:hq "$APP_DIR" "$HQ_HOME"
# Your data and sign-ins are readable by HQ only.
chmod -R go-w "$APP_DIR"
chmod 750 "$APP_DIR/data" "$HQ_HOME"
[ -f "$APP_DIR/.env" ] && chmod 600 "$APP_DIR/.env"
[ -d "$APP_DIR/config/secrets" ] && chmod -R go-rwx "$APP_DIR/config/secrets"

say "Installing HQ's Python packages (a few minutes)"
[ -x "$VENV/bin/python" ] || runuser -u hq -- python3 -m venv "$VENV"
runuser -u hq -- "$VENV/bin/pip" install -q --upgrade pip
runuser -u hq -- "$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
    if [ -z "${HQ_PASSWORD:-}" ]; then
        read -r -s -p "Choose a password for the dashboard: " HQ_PASSWORD </dev/tty; echo
    fi
    [ -n "$HQ_PASSWORD" ] || { echo "A password is required."; exit 1; }
    umask 077
    printf 'HQ_PASSWORD=%s\n' "$HQ_PASSWORD" > "$ENV_FILE"
    umask 022
fi
chmod 600 "$ENV_FILE"
grep -q '^HQ_AUTO_UPDATE=' "$ENV_FILE" || echo 'HQ_AUTO_UPDATE=1' >> "$ENV_FILE"
if [ -n "${HQ_TZ:-}" ] && ! grep -q '^HQ_TZ=' "$ENV_FILE"; then echo "HQ_TZ=$HQ_TZ" >> "$ENV_FILE"; fi

if [ "${HQ_WAITING:-}" = 1 ] && [ ! -s "$APP_DIR/data/hq.sqlite3" ]; then
    # A brand-new server: nothing runs or posts until your HQ moves in from the PC.
    (cd "$APP_DIR" && runuser -u hq -- "$VENV/bin/python" -c \
        "from hq import standby; standby.set_standby(True, reason='waiting')")
fi

say "Joining your Tailscale network"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
if ! tailscale status >/dev/null 2>&1; then
    if [ -n "${TS_AUTHKEY:-}" ]; then
        tailscale up --authkey="$TS_AUTHKEY" --hostname=agent-hq --ssh
    else
        echo "!! Not on Tailscale yet. Run:  tailscale up --hostname=agent-hq --ssh   then sign in, and run this script again."
    fi
fi

say "Setting HQ to start by itself, restart if it stops, and check itself every 5 minutes"
cat > "$UNITS/agent-hq.service" <<UNIT
[Unit]
Description=Agent HQ
After=network-online.target tailscaled.service
Wants=network-online.target
# A new version that keeps crashing (8 starts in 5 minutes) goes back to the last version that ran fine.
StartLimitIntervalSec=300
StartLimitBurst=8
OnFailure=agent-hq-rollback.service

[Service]
User=hq
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
Environment=HQ_SUPERVISED=1
Environment=PYTHONUNBUFFERED=1
ExecStartPre=-$VENV/bin/python -m hq update
ExecStart=$VENV/bin/python -m hq serve --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
# Exit code 3 is HQ restarting itself on purpose (after an update or a move), not a crash.
SuccessExitStatus=3
RestartForceExitStatus=3
UMask=0027
# On a stop or reboot HQ first lets a clip that's being posted finish.
TimeoutStopSec=900

[Install]
WantedBy=multi-user.target
UNIT

# The rollback runs from its own copy, so a broken update can't break the way back.
install -D -m 755 "$APP_DIR/deploy/cloud/rollback.sh" /usr/local/lib/agent-hq/rollback.sh

cat > "$UNITS/agent-hq-rollback.service" <<UNIT
[Unit]
Description=Agent HQ: go back to the last version that ran fine

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR
ExecStart=/bin/sh -c '/usr/local/lib/agent-hq/rollback.sh $APP_DIR && systemctl reset-failed agent-hq && systemctl start agent-hq'
UNIT

cat > "$UNITS/agent-hq-health.service" <<UNIT
[Unit]
Description=Agent HQ watchdog

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR
ExecStart=/bin/sh -c 'runuser -u hq -- $VENV/bin/python -m hq health --fix; if [ \$? -eq 2 ]; then systemctl reset-failed agent-hq; systemctl restart agent-hq; fi; exit 0'
UNIT

cat > "$UNITS/agent-hq-health.timer" <<UNIT
[Unit]
Description=Check Agent HQ every 5 minutes

[Timer]
OnBootSec=10min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable agent-hq agent-hq-health.timer >/dev/null 2>&1
systemctl stop agent-hq-health.timer 2>/dev/null || true
systemctl restart agent-hq

# Only devices on your Tailscale network can reach the server. The public internet sees nothing at all.
if grep -qi oraclecloud /sys/class/dmi/id/chassis_asset_tag 2>/dev/null; then
    # Oracle's Ubuntu already blocks everything coming in except SSH (with its own iptables rules) and asks people
    # not to use ufw, so HQ just lets your Tailscale devices in on top of those rules.
    say "Letting your Tailscale devices in (Oracle's firewall blocks everyone else)"
    for t in iptables ip6tables; do
        $t -C INPUT -i tailscale0 -j ACCEPT 2>/dev/null || $t -I INPUT 1 -i tailscale0 -j ACCEPT
    done
    command -v netfilter-persistent >/dev/null && netfilter-persistent save >/dev/null 2>&1 || true
elif ip link show tailscale0 >/dev/null 2>&1; then
    say "Locking the server to your Tailscale devices"
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    ufw allow in on tailscale0 >/dev/null
    ufw allow 41641/udp >/dev/null
    ufw --force enable >/dev/null
else
    echo "!! Tailscale isn't running, so the firewall was left alone. Set up Tailscale, then run this again."
fi

for _ in $(seq 1 60); do
    curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1 && break
    sleep 2
done
if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
    # The watchdog starts once HQ is up, so it never restarts HQ while it's still starting.
    systemctl start agent-hq-health.timer
    IP=$(tailscale ip -4 2>/dev/null | head -1 || true)
    echo
    echo "Agent HQ is running. Open http://${IP:-$(hostname)}:8000 on your PC or Mac (with Tailscale on)."
else
    echo "Agent HQ didn't start. Recent log:"
    journalctl -u agent-hq -n 40 --no-pager
    exit 1
fi
