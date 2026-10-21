# Agent HQ

A Boss that directs a team of AI agents, and Chad, the first agent, who clips creators' videos
into vertical shorts for TikTok (priority), YouTube Shorts and Instagram Reels.

```
You  ->  Boss (Claude)  ->  tasks  ->  Chad  ->  clips waiting for your approval  ->  posted to your clipping accounts
              ^                                          |
              +---------- status reports <---------------+
```

## Install (Windows)

Download `Install-Agent-HQ.bat` and double-click it. It installs Git, Python and ffmpeg if they're missing, puts HQ in
`C:\Users\<you>\CHADCLIP`, brings over your data, keys and edited config from older copies (like a ZIP in Downloads),
and adds an **Agent HQ** icon to your Desktop. Run it again any time something seems broken: it's safe to repeat.

After that you never download a ZIP or edit `.env` again:

- **Updates**: the icon gets the newest HQ from GitHub each time it opens. While HQ runs, a green "Update ready" bar
  appears on the dashboard when there's new code; press **Update and restart**. If you (or the Boss) changed a file in
  `config/`, your version is kept. Any other file you edited is saved to `data/update-backups/` first, so an edit can
  never block an update. Updates only arrive after GitHub has run every test on Windows and Linux and they all
  passed; newer changes still being tested show as "being tested" on the dashboard.
- **Settings**: press **⚙️ Settings** on the dashboard to paste API keys, tokens and options, and to turn posting
  accounts on. They're saved in `data/settings.json` (never touched by updates) and win over `.env`, which still works.
  New settings appear there by themselves when they're added to `.env.example`.

The Desktop icon opens HQ in its own window. Closing the window stops HQ (and the agents), so minimize it instead if
you want Chad to keep working. If HQ is already running from `start-hq.bat`, the icon just opens a window onto it.
If the window doesn't open, look in `data/desktop-app.log`.

## Getting started

The dashboard opens with a **Getting started** checklist: every key, account and permission HQ still needs, in the order
to do them, with a **Fix** button that jumps to the right place. In ⚙️ Settings, press **Test** next to a key to check it
works (it tests what you typed, even before you save). Ask the Boss "what's left to set up?" for the same list.

Until a real posting account is switched on, approved clips go to the **practice account**: they're saved with their
caption in `data/practice-posts/` instead of being uploaded (`HQ_PRACTICE_POSTING` changes that). To watch the whole
chain work, press **Pick a video** on the checklist and give Chad a video you made yourself.

## Run it by hand (Mac, Linux, developers)

```bash
pip install -r requirements.txt        # also needs ffmpeg installed
python -m hq serve                     # dashboard at http://127.0.0.1:8000, then add your keys under Settings
```

Other commands: `python -m hq chat` (talk to the Boss in the terminal), `python -m hq report`,
`python -m hq chad --file some.mp4` (try Chad on a local video), `python -m hq publish`, `python -m hq update`,
`python -m hq app` (the desktop window).

## Open HQ from your other computers

Keep HQ running on one computer (your Windows PC) and open its dashboard from anywhere, like your Mac:

1. Install [Tailscale](https://tailscale.com/download) on both computers and sign in with the same account.
2. On the PC, open ⚙️ Settings and set `HQ_PASSWORD` to something long.
3. On the PC, allow Tailscale devices through the Windows firewall (PowerShell as administrator, once):
   `New-NetFirewallRule -DisplayName "Agent HQ" -Direction Inbound -Protocol TCP -LocalPort 8000 -RemoteAddress 100.64.0.0/10 -Action Allow`
4. Double-click `start-hq.bat` instead of running `python -m hq serve`.
5. On the Mac, open `http://<your PC's name in Tailscale>:8000` and log in.

The PC must stay on and awake (Settings > System > Power > sleep "Never" when plugged in). To start HQ when the PC
turns on, put a shortcut to `start-hq.bat` in the Startup folder (Win+R, type `shell:startup`).

Without `HQ_PASSWORD`, HQ only listens on the computer it runs on, exactly as before. `python -m hq backup` zips the
database and settings into `data/backups`, and HQ does this by itself once a day. To move HQ to an always-on
cloud server later, see `deploy/cloud/install.sh`.

## The Boss

Chat with it on the dashboard. It reads `config/vision.md` before every conversation, assigns tasks to
agents, answers "what's going on", and sends a daily report. Tell it "remember that ..." to add to the
vision. It only approves or rejects clips when you explicitly tell it to. Without an API key it understands
`status`, `check on chad`, `clip <creator>` and `clip <link>`.

It also checks Chad's work. Say "check on Chad" (and every daily report does it too): it looks at failed or
stuck tasks, failed posts, and every clip waiting for you, and flags problems like missing captions, no
credit to the creator, weak moments, near-duplicate clips, clips over 59 seconds or missing video files.
Flagged clips show a yellow "Boss" note on their approval card. Flagging never approves, rejects or posts.

## Chad

1. Reads `config/creators.yaml`. **Creators with no `permission` value are skipped.** Only clip people who
   allow it (a clipping program or campaign, written permission, or your own content).
2. Downloads new videos (yt-dlp), transcribes them (Whisper), and asks Claude to pick the strongest moments
   with a title, caption and hashtags.
3. Cuts each moment to 1080x1920 with a blurred background and word-by-word captions (ffmpeg).
4. Puts the clips on the dashboard for you to preview, edit and approve.
5. Posts approved clips to every enabled account in `config/accounts.yaml`, TikTok first.

Tune it in `config/chad.yaml` (clips per video, length, how often it checks, caption style).

## Connecting the platforms

| Platform | What you need |
| --- | --- |
| TikTok | A developer app with the Content Posting API, and an access token per clipping account. Unaudited apps can only send clips to the account's inbox (`mode: inbox`), where you tap Post; direct posting needs TikTok's audit. |
| YouTube Shorts | A Google Cloud project with YouTube Data API v3, an OAuth client file, then `python -m hq connect-youtube <account>` once. New projects get roughly 6 uploads per day of quota. |
| Instagram Reels | A Business or Creator account linked to a Facebook page, the account's ID and token, and `HQ_PUBLIC_BASE_URL` pointing at where `data/clips` is reachable from the internet. |

Paste each account's secrets under ⚙️ Settings, then switch the account on there.

## Adding the next agent

Subclass `Agent` in `hq/agents/base.py`, implement `run(task)`, and add it to `hq/agents/__init__.py`.
The Boss, task queue, scheduler and dashboard pick it up automatically.

## Scout (campaigns)

Paid clipping campaigns (for example on Whop) tell you what to clip, how to caption it and what they pay per 1,000
views. Ask the Boss to have Scout vet one: paste the campaign's rules (and the link, and any video links they give you).
Scout pulls out the pay, budget, rules and required hashtags, rates it out of 10, flags problems, and sends it to the
dashboard (and your phone, if Relay is on) with Join and Skip buttons.

Once you join, Chad treats the campaign as a creator he has permission to clip, adds the required hashtags, and every
posted clip becomes a "to submit" entry. Scout lists those every 6 hours. After you submit a link to the campaign, tell
the Boss the views and earnings and Scout keeps the totals on the dashboard. Whop has no public API for clippers, so
the submitting and the numbers are manual for now.

### Scout finds campaigns on its own

Every 6 hours Scout reads its **inbox** (the box on the dashboard's Campaigns section: paste links or page text) and any
public feeds you list in `SCOUT_FEED_URLS` (Settings page), rates what is new with the cheap model, and puts the good ones
(`SCOUT_MIN_SCORE`, default 6) on the dashboard and your phone for a Join decision. It never joins or signs up for you,
skips campaigns that are more than 80% spent, and stops when `HQ_DAILY_BUDGET` is reached.

What it will not do: Whop's terms forbid automated access, and Discord forbids it for personal accounts, so Scout never
opens those sites. For a Whop campaign, open it in your browser and paste the page text into the inbox. Everywhere else
Scout checks `robots.txt` first and skips sites that say no.

### Scout suggests creators

Once a week (or when you ask the Boss) Scout looks at the most-watched Twitch channels, checks how many views their top
clip got today and whether their bio mentions clippers or a business contact, and lists the best on the dashboard under
**Creators to clip**. It uses only the free Twitch API with your Twitch keys and no Claude call. Scout cannot know whether
a creator allows clipping: you check their socials, Discord or a clipping campaign, then press **I can clip them** and
type how you're allowed to. That is saved in `config/streamers.yaml`, which is what lets Chad clip them.

## Pitch (clients)

Pitch finds streamers and podcasters who might pay you to clip for them and drafts a short, personal message for each.
It only drafts: every message waits in "Waiting for your OK" (dashboard and phone). Tap "I'll send it", copy the text,
and send it yourself. Pitch then reminds you to follow up after 4 days (twice at most) and keeps a Leads list.

Fill in `config/pitch.yaml` first (your name, one honest line about you, what you offer, price). Then ask the Boss
"have Pitch find 5 streamers", or give it someone you found: `{"lead": {"name": ..., "platform": ..., "handle": ...,
"contact": ..., "notes": ...}}`. Finding streamers uses the Twitch app keys in `.env`. Messages never send themselves,
because platforms ban accounts that automate this and spam laws apply to cold email (honest subject, opt-out line).

## Relay (phone)

Relay is a private Telegram bot. Message it to talk to the Boss, get each new clip as a video with Approve and
Reject buttons, and receive the daily report. It only ever answers your own Telegram account. Setup is in `.env.example`
(a bot token from @BotFather, then `python -m hq relay-id` for your ID). It stays off until both are set.

## Models and cost

Each agent uses the cheapest Claude model that does its job: the Boss on Opus 5.5, Chad on Sonnet 5.5, and every
simpler agent on Haiku 5.5 (about 40 times cheaper than Opus). Change any of them in `.env` with
`HQ_MODEL_<NAME>=...`, for example `HQ_MODEL_CHAD=claude-opus-5-5`.

The dashboard's money tile (the Ledger) shows what Claude cost today and this month, per agent. Set
`HQ_DAILY_BUDGET=2` in `.env` to stop scheduled agent work for the day once spending reaches $2.

## Safe defaults

- Nothing posts until you approve it (`HQ_REQUIRE_APPROVAL=true`).
- Each platform's failure is recorded and doesn't block the others.
- Secrets live only in `data/settings.json`, `.env` and `config/secrets/`, all git-ignored. The Settings page never
  sends a saved key back to the browser, only its last four characters.

## Clipping the top Twitch streamers

Set `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` (free app at dev.twitch.tv/console), then ask the Boss
"clip the top 10 Twitch streamers' best clips from today", or run `python -m hq chad --twitch-top 10`.
Chad ranks the channels by current viewers, takes each one's most-viewed clips from the last day, and queues
them for your approval. Streamers are only clipped once you record how you're allowed to clip them in
`config/streamers.yaml`. Kick has no ranking API Chad can rely on: give him individual Kick clip links
(`{"url": ...}` with a creator that has permission in `creators.yaml`).
