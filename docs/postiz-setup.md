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

Posting limits (posts per day, minutes between posts) apply to Postiz accounts exactly like the others.
