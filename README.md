# Vitals: personal Garmin health dashboard

One web app with two layouts: phone (iOS home-screen app) and TV (landscape, D-pad, ambient mode).

```
web/          the app (index.html + manifest + service worker + icons); data.json is generated
sync/         sync.py pulls Garmin data → web/data.json · save_key.py stores your Personal API key locally
.github/      daily GitHub Actions job: sync → AI briefing → publish to GitHub Pages
tv/           Android TV app (full-screen WebView of the TV layout) + build script
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

## Insights: how they're made
1. **`sync/analysis.py`** computes the numbers, so the model never does maths:
   - HRV z-score vs 28-day baseline, and 7-day coefficient of variation (CV)
   - resting HR drift
   - sleep debt and regularity, social jet lag, stage mix
   - ACWR, Foster monotony and strain
   - intensity distribution from heart rate zones
   - 90-day correlations, for example stress vs that night's sleep
   - Vitals Age pace of aging
2. **`sync/coach_skill.md`** is the analysis "skill": the sports-science playbook the model follows. It sets thresholds, how to read each signal, writing rules and the output schema.
3. **Gemini** (or Claude) receives the playbook plus the computed facts and returns JSON:
   - `today` (briefing)
   - `sleep`, `heart`, `activity`, `trends` (one insight per page)
   - `vitalsAge` and `latestActivity`
4. **Rule-based insights** are still computed in the app, so something useful shows even without AI.

## Activity details
The newest 40 activities get `web/acts/<id>.json`:
- downsampled heart rate, pace, elevation, cadence, power, respiration and stamina
- per-km (run) or per-5 km (ride) splits
- a GPS route **with the first and last 400 m trimmed** so the public site doesn't reveal where you start

These files aren't committed. The daily job reuses the published copies and only fetches new activities.

## Android TV app
- **Build:** `tv/build.sh`. It uses the JDK and Android SDK in `.tools/`, with no Gradle, and writes `tv/vitals-tv.apk`.
- **Install:** `.tools/android/platform-tools/adb connect 192.168.0.4:5555`, then `.tools/android/platform-tools/adb install -r tv/vitals-tv.apk`.
- **Remote:**
  - Arrows move focus.
  - OK opens things; holding OK starts ambient mode.
  - Back returns to the menu, and closes the app from the menu.
  - Menu turns ambient mode on or off.
- **Old browsers:** the TV's WebView is Chrome 74, so the deploy job converts the JavaScript to older syntax (`sync/legacy_build.py`). The CSS has fallbacks for missing flexbox `gap`.
- **No external resources:** fonts are bundled because Google Fonts is blocked on networks in mainland China.

## Privacy note
The code repo contains no health data. `data.json` only exists on the published site, so anyone who has the URL can read it. Keep the URL to yourself.
