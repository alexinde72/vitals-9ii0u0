# Vitals: personal Garmin health dashboard

One web app with two layouts: phone (iOS home-screen app) and TV (landscape, D-pad, ambient mode).

```
web/          the app (index.html + manifest + service worker + icons); data.json is generated
sync/         sync.py pulls Garmin data → web/data.json · save_key.py stores your Personal API key locally
.github/      daily GitHub Actions job: sync → AI briefing → publish to GitHub Pages
tv/           (next phase) Android TV wrapper APK
```

## How it works
1. Every morning at 09:30 (Asia/Shanghai), GitHub Actions runs `sync/sync.py`.
2. The sync swaps your **Garmin Personal API key** for a 24-hour token and fetches the last 10 days. The first run fetches 364 days. It merges them with the history already published.
3. Recovery % is computed from HRV, resting heart rate and sleep against your 30-day baseline, because the Personal API has no Training Readiness.
4. If `ANTHROPIC_API_KEY` is set, Claude writes the daily briefing. Rule-based insights are always computed in the app.
5. The `web/` folder is published to GitHub Pages. Phones and TVs load `data.json` from there.

## Run locally
```bash
.tools/bin/uv run --python 3.12 --with garmin-connect-personal-api-python sync/save_key.py   # once
.tools/bin/uv run --python 3.12 --with garmin-connect-personal-api-python sync/sync.py        # real data
python3 sync/sync.py --sample                                                                 # fake data
python3 -m http.server 8766 --directory web
```
- Phone layout: `http://localhost:8766`
- TV layout: `http://localhost:8766/?tv=1`

## Setup (one time)
1. **Garmin key**: create it at connect.garmin.com/app/settings/personalApiToken. Keys expire after 30 days to 1 year, and Garmin emails you a week before.
2. **GitHub repo**: create a *public* repo with a hard-to-guess name (Pages on private repos needs a paid plan) and push this folder.
3. **Secrets** (repo → Settings → Secrets and variables → Actions):
   - `GARMIN_PERSONAL_API_KEY`: your Garmin key.
   - `ANTHROPIC_API_KEY` (optional): enables the AI briefing.
4. **Pages**: repo → Settings → Pages → Source: **GitHub Actions**.
5. **First run**: Actions → "Sync Garmin & deploy" → Run workflow.
6. **iPhone**: open the Pages URL in Safari → Share → Add to Home Screen.

**When the key expires**, the app shows "Sync overdue". Create a new key and replace the `GARMIN_PERSONAL_API_KEY` secret.

## Privacy note
The code repo contains no health data. `data.json` only exists on the published site, so anyone who has the URL can read it. Keep the URL to yourself.
