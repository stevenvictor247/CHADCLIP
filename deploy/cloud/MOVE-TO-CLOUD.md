# Run Agent HQ on a cloud server (so it runs with your PC off)

Everything is done from HQ's **🚚 Move HQ** page (Settings → Move HQ). No terminal, no SSH. You open the cloud HQ from
your PC and Mac over Tailscale, with your usual password.

Cost: **$0** on Oracle Cloud's Always Free plan (Ampere A1, 4 processors, 24 GB memory, Ubuntu 24.04).
If Oracle has no free servers left, Vultr (4 GB, Chicago, about $24 a month with backups) works the same way.

## 1. Make the server (one time)
1. On the Move HQ page, paste a Tailscale auth key and press **Make my server setup text**, then **Copy**.
2. Make the server (the page lists every choice):
   - Oracle: Compute → Instances → Create instance, name `agent-hq`, Canonical Ubuntu 24.04, shape VM.Standard.A1.Flex
     (4 OCPUs, 24 GB), 100 GB boot volume, and paste the text under Show advanced options → Management → cloud-init script.
     Upgrading the account to Pay As You Go keeps it $0 and stops Oracle reclaiming a quiet free server.
   - Vultr: Cloud Compute, Shared CPU, Chicago, Ubuntu 24.04, 4 GB, Automatic Backups, paste into Cloud-Init User-Data.
3. Wait about 10 minutes. The server installs HQ by itself (`install.sh`, log in `/var/log/agent-hq-install.log`) and
   waits on standby: it can't post anything until your HQ moves in.

## 2. Move HQ (one click)
On the PC's Move HQ page: **Find my server** → **Check** → **Move HQ now**. HQ waits for any post in progress to
finish, packs the database, Settings, keys, sign-ins, clips still to post and football data, sends it over Tailscale, and
waits until the cloud HQ is running. Then the PC goes on standby ("HQ runs in the cloud now", with a link) and the desktop
icon opens the cloud HQ. Your Windows paths are fixed for Linux and your time zone comes along.

## 3. After the move
- In the Tailscale admin page: Machines → agent-hq → ⋯ → **Disable key expiry**.
- Cloud HQ → Settings → **Google Drive**: connect it, so the football folders sync (files are never deleted; a clash
  keeps both copies as "(HQ copy)").
- Cloud HQ → Settings → **HQ_PRINTER_EMAIL**: your printer's HP ePrint address. Thursday's print goes out by email
  (one file per email) through the Pitch Gmail. In HP Smart, allow that Gmail as a sender.

## What the server does by itself
- Starts at boot, restarts if HQ crashes, and its own restarts (after an update or move) are normal.
- Updates itself, only to versions that passed every test and never mid-post. If a new version crashes 8 times in
  5 minutes, `rollback.sh` goes back to the last version that ran fine and skips the bad one.
- A watchdog every 5 minutes: restarts HQ if two checks in a row fail, and texts you about a full disk, an old backup
  or the Tailscale key expiring. Optional `HQ_HEALTHCHECK_URL` (healthchecks.io) tells you if the whole server is down.
- Daily backups, also copied (without secrets) to "My Drive/Agent HQ backups" once Drive is connected.
- Security updates install themselves (reboots at 04:30 if needed). Only your Tailscale devices can reach it.

## Never posting twice
Only one copy runs the agents. The copy that moved away is on standby (read-only). If both are ever switched on, each
checks the other over Tailscale (`HQ_PEER_URL`), and the one that took over last stops and tells you.

## Moving back to the PC
Start HQ on the PC (it opens on standby), then on the cloud HQ's Move HQ page: **Move HQ to another computer** with the
PC's Tailscale address. Your Windows folders come back as they were.

By hand on any computer: `python -m hq standby status|on|off`, `python -m hq health`, `python -m hq rollback`.

## Honest limits
- Clipping runs on the server's processor (no graphics card), so making clips is slower than on a gaming PC.
- YouTube sometimes blocks downloads from cloud servers. Twitch and Kick clips are normally fine.
