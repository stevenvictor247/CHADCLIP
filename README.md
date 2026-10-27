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

Keep HQ running on your Windows PC and open its dashboard from anywhere, like your Mac:

1. On the PC, double-click `Setup-Mac-Access.bat` in the CHADCLIP folder. It installs and signs in to
   [Tailscale](https://tailscale.com/download), asks for an HQ password, lets only your Tailscale devices through the
   firewall (click Yes on the prompt), keeps the PC awake while plugged in, runs HQ in the background at every sign-in,
   and saves your Mac address to `Agent HQ on my Mac.txt` on the Desktop.
2. On the Mac, install Tailscale, sign in with the same account, and open that address.

HQ then runs in a minimized `start-hq` window. The Agent HQ icon still opens it on the PC, and closing that window
no longer stops HQ. The PC has to stay on, plugged in and signed in.

Without `HQ_PASSWORD`, HQ only listens on the computer it runs on, exactly as before. `python -m hq backup` zips the
database and settings into `data/backups`, and HQ does this by itself once a day. To move HQ to an always-on
cloud server later, see `deploy/cloud/install.sh`.

## Hook Lab

Chad gives every clip three opening lines in different styles (question, bold claim, tease), labeled A, B and C. Tap
one on the clip's approval card and it becomes the first line of the caption. Tally saves the chosen style next to the
clip's views, and once 20 counted clips have a chosen hook it reports which style got the most views. From then on
Chad writes that style as option A. It costs nothing extra: the lines come from Chad's existing Claude call (templates
fill in when there's no key). Until there are enough views the report says "no winner yet".

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
| YouTube Shorts | A Google Cloud project with YouTube Data API v3 and a Desktop-app OAuth client. Paste its file under **Connect YouTube** in ⚙️ Settings and press **Open Google sign-in**, approve, then paste back the address you land on (works from the Mac). Publish the consent screen first or Google signs you out every 7 days. New projects get roughly 6 uploads per day of quota. |
| Instagram Reels | A Business or Creator account linked to a Facebook page and a Meta developer app. Follow **Connect Instagram** in ⚙️ Settings: paste the app's ID and secret, then a token from the Graph API Explorer, and HQ swaps it for one that doesn't expire. Clips are uploaded straight to Instagram, so no public address is needed (`HQ_PUBLIC_BASE_URL` is optional). |

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

**Web search (new).** Once a day Scout asks Claude to search the open web for campaigns that are open right now, with no
pasting needed. Anthropic runs the searches (about 6 cents a day plus a little Claude time, counted in the Ledger), Whop and
Discord are excluded from the results, and every find is rated like the rest. Pages are read only where `robots.txt`
allows; otherwise the rating uses the search excerpt and the campaign is marked "web (excerpt only)". Turn it off with
`SCOUT_WEB_SEARCH=0`; use `HQ_MODEL_SCOUT_SEARCH=claude-opus-5-5` for a deeper search. It needs web search switched on for
your Anthropic organization (Console, Settings, Privacy).

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
and send it yourself. Pitch then reminds you to follow up after 4 days (twice at most) and keeps a Leads list. With Gmail set up, a follow-up for a lead with an email is drafted for you and waits for "Send follow-up"; nothing sends without your tap.

Fill in `config/pitch.yaml` first (your name, one honest line about you, what you offer, price). Then ask the Boss
"have Pitch find 5 streamers", or give it someone you found: `{"lead": {"name": ..., "platform": ..., "handle": ...,
"contact": ..., "notes": ...}}`. Finding streamers uses the Twitch app keys in `.env`. Messages never send themselves,
because platforms ban accounts that automate this and spam laws apply to cold email (honest subject, opt-out line).

**One-click email.** Put your Gmail address and an app password (myaccount.google.com/apppasswords) in Settings and fill
in your postal address. For a lead with an email address the card then says "Send email": nothing is sent until you press
it, and then HQ sends that one message from your Gmail. Safeguards: one email per lead ever, a daily cap
(`daily_send_cap`, default 10, never above 20), your opt-out line and postal address added to every message, and a
do-not-contact list (set a lead to `do_not_contact`, or tell the Boss `{"do_not_contact": "email"}`). If a send fails or
is blocked, the same draft returns to Waiting for your OK. Leads without an email stay copy-and-send-yourself.

## Rally (Saturday college football posts)

Rally drafts short text-and-card posts for TikTok and Shorts about public college football storylines (upset watch,
rankings, rivalry history, weekly stat facts). It reads a free public rankings feed (or facts you paste), asks the
cheap Claude model for 5 posts, then checks them in code: any number not in the facts, or any mention of logos, film or
highlights, is thrown out. Each post gets a plain 1080x1920 card (no school marks) and waits in Approvals. Approving
only hands you the text and card to post yourself; Rally never posts. Once a day it checks for free whether a round is
due (no round if posts are still waiting, one was drafted this week, or the season in `config/rally.yaml` is over).
After you post, tell the Boss the views (`{"views": {"id": 4, "views": 1200}}`) and `{"report": true}` shows which
topics work. Set the account's niche in `config/rally.yaml`.

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

## Sweep (the janitor)

Sweep is the janitor in HQ Town. It never calls Claude itself, so it costs nothing, and it keeps working on a day
when the Claude budget is spent. Every few hours it checks what Claude is costing and tidies up after the other
agents; once a day (around `HQ_SWEEP_REPORT_HOUR`, 8 by default) it sends one report to the **Sweep** card on the
dashboard and to your phone through Relay.

What it fixes by itself, always logged in Activity and either undoable or harmless:

- a job stuck on "running" after a crash goes back in the queue once, then is closed as failed
- a job that failed on a network or overload error is retried once
- source downloads older than a week, rejected clips, old practice posts and logs over 5 MB go to
  `data/sweep/trash` (the **Put back** button restores them for 7 days, then they are deleted)
- an idle Boss conversation that has grown huge is closed, so the next chat starts small (the old one stays saved)

What it only reports: a budget nearly or fully spent, a day costing double the usual, an agent making a burst of
calls (a possible loop), the same job failing again and again, prompts that aren't being cached, a model with no
price on file, and a nearly full disk. If a small job runs on a pricier model than it needs, Sweep asks in
**Waiting for your OK** before changing that agent's model, and you can change it back in Settings. Sweep never
posts, emails, spends money or changes settings or keys without your approval.

The Boss's chat also uses prompt caching now, so the unchanged start of each conversation is billed at a tenth of the
price.

## Muse (the Creative Director)

Muse lives in the Writers' Room on Market Street in HQ Town and thinks up new ways for HQ to make money and run better:
new businesses, new agents, add-ons to what HQ already does, and HQ upgrades. Its ideas are on the **Ideas** tab.

- About once a week (`HQ_MUSE_EVERY_DAYS`, 7) the Boss sends Muse on its round: one Claude call (Sonnet, medium
  effort) through Claude's half-price batch queue, up to about $0.07, asking only for as many ideas as there's room
  for (up to `HQ_MUSE_IDEAS`, 5, open at once). The ideas land within the hour. Before that, free checks in code skip
  the round when it's too soon, when there's no room for at least 3 new ideas because the last ones still wait for
  your answer, or when its monthly cap (`HQ_MUSE_MONTHLY_BUDGET`, $3) or the day's `HQ_DAILY_BUDGET` would be passed.
  **Brainstorm now** (optionally with a topic) answers in a minute at full price (up to about $0.14) and skips the
  wait but never the caps.
- Code, not Claude, drops ideas that repeat anything already built, already shown to you on an ideas page, parked
  (the cloud server) or turned down, and anything against HQ's rules, then ranks the rest by expected first-year
  profit for each hour of work.
- The best `HQ_MUSE_TO_APPROVALS` (3) go to **Waiting for your OK** and your phone. **Build it** sends the idea's
  build brief to Claude, which builds it in CHADCLIP and opens a PR (once `HQ_BUILD_TOKEN` and `HQ_BUILD_URL`
  are set: on claude.ai make a Code task for CHADCLIP with no schedule, Add trigger, API, Generate token).
  Without the token you get the brief to paste to Claude yourself; **Not for me** asks why (one tap), and Muse learns from your answers. Muse never builds,
  buys, posts or signs up for anything itself.

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

## Tally (views)

Tally counts the views on every clip HQ posted, twice a day. It copies them into your campaign submissions (views
only go up; the pay you typed in is never changed), works out what the campaigns should pay from each campaign's rate,
and writes a short note of the clips that did best, which Chad reads when he picks moments. It never calls Claude, so
it costs nothing. YouTube is counted through the same sign-in you make under **Connect YouTube** in ⚙️ Settings.
TikTok inbox uploads have no video id until you post them in the app, so TikTok views come later.

## Podcast clip packs

Packs turns one podcast episode into a $49 pack: 5 captioned vertical clips (Chad's editor) plus Recap's three titles,
description, chapters and 5 post ideas. Ask the Boss for a pack, or queue a Packs task with
`{"client": "podcast name", "owner": "emailed me ep 12 and said yes to clips, 26 Oct", "file": "path/to/episode.mp4"}`.
Packs refuses without that permission note, a video of 10+ minutes and Whisper, checks all of that in code before any
Claude spend, and never makes the same episode twice. The finished folder (`data/packs/`) waits in Approvals; approving
it shows you the message to send, including a request for a testimonial. Packs never sends, posts or takes payment:
create the $49 Stripe payment link yourself and send it with the files.
