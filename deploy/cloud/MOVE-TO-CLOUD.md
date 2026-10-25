# Move Agent HQ to a cloud server (so it runs with your PC off)

Cost: about $10 a month (Hetzner CX32, Ubuntu 24.04). You open HQ from any computer over Tailscale, with your password.

## One time: set up the server
1. Make a Hetzner account, create a server (Ubuntu 24.04, CX32). Open its console (or SSH in as root).
2. Put Tailscale on it: `curl -fsSL https://tailscale.com/install.sh | sh` then `tailscale up`, and sign in with the same account as your PC.
3. Get HQ and install it:
   ```
   git clone https://github.com/stevenvictor247/CHADCLIP /opt/agent-hq
   bash /opt/agent-hq/deploy/cloud/install.sh
   ```
   It asks for a dashboard password and your time zone. It then starts HQ, restarts it if it crashes or the server reboots,
   updates it by itself (only to versions that passed every test, and never in the middle of a clip), and locks the server so only your Tailscale devices can reach it.

## Moving your HQ over (only one computer runs the agents at a time)
1. On your PC, in the HQ folder, with HQ closed: `python -m hq handoff`.
   It saves a backup zip in `data\backups` and puts the PC on **standby**, so the PC can't post anything.
2. Copy that zip to the server (from PowerShell: `scp data\backups\hq-backup-XXXX.zip root@<server tailscale name>:/tmp/`).
3. On the server: `systemctl stop agent-hq`, then `cd /opt/agent-hq && sudo -u hq .venv/bin/python -m hq restore /tmp/hq-backup-XXXX.zip`, then `systemctl start agent-hq`.
   This brings your database, Settings, keys, YouTube sign-ins, TikTok sign-in, what was already clipped, and the football data.
4. Open `http://<server tailscale name>:8000`. Instagram, Twitch, Telegram and Gmail keys came along in Settings. If a sign-in ever says expired, press Connect again in Settings.

Clip video files stay on the PC (big). Pending clips need re-making or `python -m hq backup --with-clips` before the move.

## Going back to the PC
Run `python -m hq handoff` on the server, copy the zip to the PC, run `python -m hq restore <zip>` there, and start HQ. Restoring turns the PC back on and the server stays on standby.
Check any computer with `python -m hq standby status`. The dashboard shows a "standby" bar on a copy that is off duty.

## What can't move
- **Thursday printing** needs your PC and its printer. Keep Thursday print on the PC (or leave the PC copy's football folder alone).
- Football Inbox/Outbox folders in Google Drive are synced to the PC, not the server.
