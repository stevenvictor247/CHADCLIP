# Agent HQ

A Boss that directs a team of AI agents, and Chad, the first agent, who clips creators' videos
into vertical shorts for TikTok (priority), YouTube Shorts and Instagram Reels.

```
You  ->  Boss (Claude)  ->  tasks  ->  Chad  ->  clips waiting for your approval  ->  posted to your clipping accounts
              ^                                          |
              +---------- status reports <---------------+
```

## Run it

```bash
pip install -r requirements.txt        # also needs ffmpeg installed
cp .env.example .env                   # add ANTHROPIC_API_KEY
python -m hq serve                     # dashboard at http://127.0.0.1:8000, worker runs in the same process
```

Other commands: `python -m hq chat` (talk to the Boss in the terminal), `python -m hq report`,
`python -m hq chad --file some.mp4` (try Chad on a local video), `python -m hq publish`.

## The Boss

Chat with it on the dashboard. It reads `config/vision.md` before every conversation, assigns tasks to
agents, answers "what's going on", and sends a daily report. Tell it "remember that ..." to add to the
vision. It only approves or rejects clips when you explicitly tell it to. Without an API key it understands
`status`, `clip <creator>` and `clip <link>`.

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

Set `enabled: true` on an account once its secrets are in `.env`.

## Adding the next agent

Subclass `Agent` in `hq/agents/base.py`, implement `run(task)`, and add it to `hq/agents/__init__.py`.
The Boss, task queue, scheduler and dashboard pick it up automatically.

## Safe defaults

- Nothing posts until you approve it (`HQ_REQUIRE_APPROVAL=true`).
- Each platform's failure is recorded and doesn't block the others.
- Secrets live only in `.env` and `config/secrets/`, both git-ignored.

## Clipping the top Twitch streamers

Set `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` (free app at dev.twitch.tv/console), then ask the Boss
"clip the top 10 Twitch streamers' best clips from today", or run `python -m hq chad --twitch-top 10`.
Chad ranks the channels by current viewers, takes each one's most-viewed clips from the last day, and queues
them for your approval. Streamers are only clipped once you record how you're allowed to clip them in
`config/streamers.yaml`. Kick has no ranking API Chad can rely on: give him individual Kick clip links
(`{"url": ...}` with a creator that has permission in `creators.yaml`).
