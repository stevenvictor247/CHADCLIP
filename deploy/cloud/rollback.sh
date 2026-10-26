#!/usr/bin/env bash
# Puts Agent HQ back on the last version that ran fine on this server, when a new version won't start.
#
# systemd runs this when HQ fails 8 times in 5 minutes (see install.sh, which keeps a copy at
# /usr/local/lib/agent-hq/rollback.sh so a broken update can't break the rollback too). It's plain bash and git on
# purpose: it must work even when the new Python code can't even be loaded.
# - The good version is data/good-version.txt, written by the watchdog after HQ has run fine for 10 minutes.
# - Your edited config/ files (vision, accounts, creators...) are kept.
# - The bad version goes in data/bad-version.txt, so the updater skips it and waits for a newer one.
# Exit code 0 = rolled back (start HQ again), 1 = nothing to roll back to, 2 = HQ isn't stuck (systemd also calls this
# after a single crash, which a normal restart fixes, so with --if-stuck it only acts once systemd gave up restarting
# HQ: the unit is "failed" then, while after a single crash it's waiting to restart).
set -u
APP_DIR="${1:-/opt/agent-hq}"
if [ "${2:-}" = --if-stuck ] && [ "$(systemctl show -P ActiveState agent-hq 2>/dev/null)" != failed ]; then
    exit 2
fi
DATA="${HQ_DATA_DIR:-$APP_DIR/data}"
cd "$APP_DIR" || exit 1
as_hq() { if [ "$(id -u)" = 0 ] && id hq >/dev/null 2>&1; then runuser -u hq -- "$@"; else "$@"; fi; }

notify() {   # a Telegram message, if Relay is set up (read straight from the settings file, no HQ code needed)
    python3 - "$DATA" "$APP_DIR" "$1" <<'PY' || true
import json, os, sys, urllib.parse, urllib.request
data, root, text = sys.argv[1:4]
env = {}
try:
    for line in open(os.path.join(root, ".env"), encoding="utf-8"):
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
except OSError:
    pass
try:
    env.update(json.load(open(os.path.join(data, "settings.json"), encoding="utf-8")))
except (OSError, ValueError):
    pass
token, owner = env.get("TELEGRAM_BOT_TOKEN", "").strip(), env.get("TELEGRAM_OWNER_ID", "").strip()
if token and owner:
    body = urllib.parse.urlencode({"chat_id": owner, "text": "🩺 " + text}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=30)
PY
}

good=$(cat "$DATA/good-version.txt" 2>/dev/null | tr -d '[:space:]')
head=$(as_hq git rev-parse HEAD)
if [ -z "$good" ] || [ "$good" = "$head" ]; then
    notify "HQ won't start, and there's no earlier version that ran fine here to go back to. Ask Claude to look at the server."
    echo "Nothing to roll back to."
    exit 1
fi

keep=$(mktemp -d)
as_hq git diff --name-only HEAD -- config/ | while IFS= read -r f; do
    [ -f "$f" ] && mkdir -p "$keep/$(dirname "$f")" && cp -p "$f" "$keep/$f"
done
reqs=$(sha256sum requirements.txt 2>/dev/null)
as_hq git reset -q --hard "$good" || { echo "git reset failed"; exit 1; }
if [ -d "$keep/config" ]; then
    cp -rp "$keep/config/." config/
    [ "$(id -u)" = 0 ] && chown -R hq:hq config
fi
rm -rf "$keep"
echo "$head" > "$DATA/bad-version.txt"
[ "$(id -u)" = 0 ] && chown hq:hq "$DATA/bad-version.txt"
if [ "$(sha256sum requirements.txt 2>/dev/null)" != "$reqs" ] && [ -x .venv/bin/pip ]; then
    as_hq .venv/bin/pip install -q -r requirements.txt
fi
notify "A new HQ version (${head:0:7}) wouldn't start, so I went back to the last one that worked (${good:0:7}). HQ takes the next update once it's fixed."
echo "Rolled back from ${head:0:7} to ${good:0:7}."
exit 0
