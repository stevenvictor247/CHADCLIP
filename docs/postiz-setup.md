# Posting through Postiz (optional)

Postiz is a free posting service you run on your own PC. HQ sends approved clips to it, and Postiz posts them to
TikTok, Instagram and YouTube. HQ only talks to Postiz over the web; none of Postiz's code is inside HQ (Postiz is
AGPL-3.0, so it stays a separate program).

Nothing changes until you do all of this. Clips still need your Approve tap before anything is sent.

## 1. Install Postiz on your Windows PC (about 20 minutes)
1. Install **Docker Desktop** from docker.com and start it. Restart the PC if it asks.
2. Follow Postiz's own "Docker Compose" guide at https://docs.postiz.com/installation/docker-compose . Copy their
   `docker-compose.yaml` into a new folder, set `MAIN_URL`, `FRONTEND_URL` and `NEXT_PUBLIC_BACKEND_URL` to
   `http://localhost:5000` (with `/api` on the backend one, as their guide shows), then run `docker compose up -d`.
3. Open http://localhost:5000 and create your account.

## 2. Connect TikTok inside Postiz
Postiz needs its own TikTok developer app keys (`TIKTOK_CLIENT_ID` and `TIKTOK_CLIENT_SECRET` in its compose file).
TikTok's audit rules still apply: until TikTok approves the app, posts only reach the inbox as drafts. In Postiz press
**Add Channel**, pick TikTok and sign in to the clipping account. Instagram and YouTube work the same way.

## 3. Tell HQ about it
1. In Postiz: **Settings > Developers**, copy the **Public API key**.
2. In HQ **Settings > Chad**, fill **POSTIZ_URL** (`http://localhost:5000`) and **POSTIZ_API_KEY**, then press **Test**.
   The test lists each Postiz channel with its **id**.
3. In `config/accounts.yaml`, find the `postiz_tiktok` entry, paste that id into `integration_id` and set
   `enabled: true`. For the TikTok inbox-only phase, add `mode: inbox` so Postiz drops it in your TikTok inbox instead.
4. Switch off the old `tiktok_main` entry so a clip isn't posted twice.
5. Keep **Practice posting** on for the first clip, then turn it off.

## 4. Add more TikTok accounts (optional)
1. In Postiz press **Add Channel**, pick TikTok and sign in to the next account. Repeat for each account.
2. In HQ **Settings > Chad**, press **Test** next to POSTIZ_API_KEY. It lists every Postiz channel with its **id**.
3. Under **Posting accounts** use **Add another Postiz channel**: give it a short name (like `postiz_tiktok_2`),
   paste the channel id, add a label you'll recognise, then **Save and restart HQ**. It starts switched off.
4. Switch it on, and press its **Test** button. Set **Most posts a day** for it if it is a new account.
   Every account keeps its own limits, so brand-new accounts can start at 1 or 2 a day.

**How clips are shared out.** TikTok treats the same video on many accounts as spam, so Postiz accounts of the same
kind take turns: each approved clip goes to just ONE of them, the account with the fewest posts today (then the one
that has waited longest). Over a day that gives every account different clips. If every account is at its limit the
clip waits for tomorrow. To make an account post every clip anyway, set **Take turns** to *No* for it.

Clips still only post after you approve them, and the daily limit (HQ_MAX_POSTS_PER_DAY, or the account's own
limit) and Pause All apply to each account. With two accounts at 4 a day, Chad can make up to 8 clips a day worth of
posting, so the daily clip cap (HQ_MAX_CLIPS_PER_DAY) is what to raise if you want more.

Posting limits (posts per day, minutes between posts) apply to Postiz accounts exactly like the others.
