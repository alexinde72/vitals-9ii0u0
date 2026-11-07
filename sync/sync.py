#!/usr/bin/env python3
"""Pull health data from the Garmin Connect Personal API and write web/data.json.

Usage:
  python sync.py --sample              # write realistic fake data (no Garmin needed)
  python sync.py                       # incremental sync (merges with existing data)
  python sync.py --backfill 365        # (re)fetch the last N days

Env:
  GARMIN_PERSONAL_API_KEY  Personal API key (else ~/.config/garmin/connect-personal-api-key)
  PREVIOUS_DATA_URL   URL of the currently deployed data.json to merge with
  GEMINI_API_KEY / ANTHROPIC_API_KEY   optional: write an AI daily briefing (Gemini preferred)
"""
import argparse
import datetime as dt
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data.json"
HISTORY_DAYS = 400
MAX_ACTIVITIES = 150


# ---------------------------------------------------------------- helpers
def g(obj, *path, default=None):
    """Safe nested get: g(d, 'a', 'b', 0, 'c')."""
    cur = obj
    for p in path:
        if cur is None:
            return default
        try:
            cur = cur[p]
        except (KeyError, IndexError, TypeError):
            return default
    return default if cur is None else cur


def num(v, nd=None):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    if nd == 0 or (nd is None and f == int(f)):
        return int(round(f))
    return round(f, nd) if nd is not None else f


def iso(d):
    return d.strftime("%Y-%m-%d")


def call(fn, *a, **k):
    for attempt in range(3):
        try:
            return fn(*a, **k)
        except Exception as e:  # noqa: BLE001 - Garmin raises many kinds
            msg = str(e)
            if "429" in msg or "Too Many" in msg:
                time.sleep(20 * (attempt + 1))
                continue
            if attempt == 2:
                print("  ! %s failed: %s" % (getattr(fn, "__name__", fn), msg[:160]), file=sys.stderr)
                return None
            time.sleep(2)
    return None


# ---------------------------------------------------------------- normalise (Garmin Personal API)
def local_ms_to_iso(ms):
    """Garmin '...TimestampLocal' values are local wall-clock time encoded as UTC epoch ms."""
    if ms is None:
        return None
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def norm_summary(s):
    st = g(s, "stress", "avgLevel")
    mod, vig = g(s, "intensityMinutes", "moderate"), g(s, "intensityMinutes", "vigorous")
    sleep_bb = None
    for ev in g(s, "bodyBattery", "activityEvents", default=[]) or []:
        if ev.get("eventType") == "SLEEP" and ev.get("bodyBatteryImpact") is not None:
            sleep_bb = (sleep_bb or 0) + ev["bodyBatteryImpact"]
    return {
        "date": s.get("calendarDate"),
        "steps": num(g(s, "movement", "steps", "value")),
        "stepGoal": num(g(s, "movement", "steps", "goal")),
        "distance": num(g(s, "movement", "steps", "distanceInMeters"), 0),
        "floors": num(g(s, "movement", "floorsAscended", "value"), 0),
        "activeKcal": num(g(s, "calories", "burnedActive")),
        "totalKcal": num(g(s, "calories", "burnedTotal")),
        "rhr": num(g(s, "heartRate", "restingValue")),
        "minHr": num(g(s, "heartRate", "minValue")),
        "maxHr": num(g(s, "heartRate", "maxValue")),
        "stress": num(st) if st is not None and st >= 0 else None,
        "bbHigh": num(g(s, "bodyBattery", "maxValue")),
        "bbLow": num(g(s, "bodyBattery", "minValue")),
        "bbCharged": num(g(s, "bodyBattery", "chargedValue")),
        "bbDrained": num(g(s, "bodyBattery", "drainedValue")),
        "bbLatest": num(g(s, "bodyBattery", "latestValue")),
        "intensity": (mod or 0) + 2 * (vig or 0) if (mod is not None or vig is not None) else None,
        "spo2": num(g(s, "pulseOx", "avgValue")),
        "resp": num(g(s, "respiration", "avgValue"), 1),
        "_sleepBB": sleep_bb,
    }


def norm_sleep(d, sleep_bb=None):
    if not d or not d.get("sleepTimeSeconds"):
        return None
    need = num(g(d, "sleepNeed", "actual"))
    return {
        "score": num(g(d, "sleepScores", "overall", "value")),
        "quality": g(d, "sleepScores", "overall", "qualifierKey"),
        "total": num(d.get("sleepTimeSeconds")),
        "deep": num(d.get("deepSleepSeconds")) or 0,
        "light": num(d.get("lightSleepSeconds")) or 0,
        "rem": num(d.get("remSleepSeconds")) or 0,
        "awake": num(d.get("awakeSleepSeconds")) or 0,
        "start": local_ms_to_iso(d.get("sleepStartTimestampLocal")),
        "end": local_ms_to_iso(d.get("sleepEndTimestampLocal")),
        "resp": num(d.get("averageRespirationValue"), 1),
        "spo2": num(d.get("averageSpO2Value")),
        "stress": num(d.get("avgSleepStress")),
        "avgHr": num(d.get("avgHeartRate")),
        "bbChange": sleep_bb,
        "need": need * 60 if need else None,
        "feedback": d.get("sleepScoreFeedback"),
        "insight": d.get("sleepScoreInsight"),
    }


def norm_hrv(h):
    if not h or not h.get("lastNightAvg"):
        return None
    return {
        "night": num(h.get("lastNightAvg")),
        "weekly": num(h.get("weeklyAvg")),
        "status": h.get("status"),
        "low": num(g(h, "baseline", "balancedLow")),
        "high": num(g(h, "baseline", "balancedUpper")),
    }


def norm_activity(a):
    zones = [num(a.get("hrTimeInZone_%d" % i), 0) or 0 for i in range(1, 6)]
    start = (a.get("startTimeLocal") or "").replace(" ", "T")
    return {
        "id": a.get("activityId"),
        "name": a.get("activityName"),
        "type": g(a, "activityType", "typeKey", default="other"),
        "start": start,
        "duration": num(a.get("duration"), 0),
        "distance": num(a.get("distance"), 0),
        "avgHr": num(a.get("averageHR"), 0),
        "maxHr": num(a.get("maxHR"), 0),
        "kcal": num(a.get("calories"), 0),
        "elevation": num(a.get("elevationGain"), 0),
        "avgSpeed": num(a.get("averageSpeed"), 3),
        "teAer": num(a.get("aerobicTrainingEffect"), 1),
        "teAna": num(a.get("anaerobicTrainingEffect"), 1),
        "teLabel": a.get("trainingEffectLabel"),
        "load": num(a.get("activityTrainingLoad"), 0),
        "bb": num(a.get("differenceBodyBattery")),
        "zones": zones if any(zones) else None,
    }


def minute_series(values, ts_index=0, val_index=1, step=5):
    """[[epoch_ms, value], ...] -> [[minuteOfDay, value]] in local time, downsampled."""
    out = []
    last = -999
    for row in values or []:
        if not isinstance(row, (list, tuple)) or len(row) <= max(ts_index, val_index):
            continue
        ts, v = row[ts_index], row[val_index]
        if ts is None or v is None or (isinstance(v, (int, float)) and v < 0):
            continue
        t = dt.datetime.fromtimestamp(ts / 1000)
        m = t.hour * 60 + t.minute
        if m - last >= step:
            out.append([m, v])
            last = m
    return out


# ---------------------------------------------------------------- recovery (computed)
def add_recovery(days):
    """Garmin's Personal API has no Training Readiness, so compute a Whoop-style recovery score:
    HRV and resting HR against your own 30-day baseline, plus last night's sleep."""
    def stats(vals):
        v = [x for x in vals if x is not None]
        if len(v) < 5:
            return None, None
        m = sum(v) / len(v)
        sd = (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5 or 1
        return m, sd

    for i, d in enumerate(days):
        if d.get("readiness") and not d["readiness"].get("computed"):
            continue
        prior = days[max(0, i - 30):i]
        hm, hs = stats([g(x, "hrv", "night") for x in prior])
        rm, rs = stats([x.get("rhr") for x in prior])
        parts, weights = [], []
        hrv = g(d, "hrv", "night")
        if hrv is not None and hm is not None:
            parts.append(max(-2.5, min(2.5, (hrv - hm) / hs))); weights.append(0.5)
        if d.get("rhr") is not None and rm is not None:
            parts.append(max(-2.5, min(2.5, -(d["rhr"] - rm) / rs))); weights.append(0.25)
        sl = d.get("sleep")
        if sl and sl.get("score") is not None:
            parts.append((sl["score"] - 70) / 15); weights.append(0.25)
        elif sl and sl.get("total"):
            parts.append((sl["total"] / (sl.get("need") or 28800) - 0.9) / 0.1); weights.append(0.25)
        if not weights or (hrv is None and not sl):
            d["readiness"] = None
            continue
        comp = sum(p * w for p, w in zip(parts, weights)) / sum(weights)
        score = int(round(max(1, min(99, 58 + 22 * comp))))
        d["readiness"] = {"score": score, "level": "HIGH" if score >= 67 else "MODERATE" if score >= 34 else "LOW", "computed": True}


# ---------------------------------------------------------------- garmin
def chunks(start, end, size):
    s = start
    while s <= end:
        e = min(end, s + dt.timedelta(days=size - 1))
        yield s, e
        s = e + dt.timedelta(days=1)


def as_list(r, key=None):
    if isinstance(r, list):
        return r
    if isinstance(r, dict):
        if key and isinstance(r.get(key), list):
            return r[key]
        for v in r.values():
            if isinstance(v, list):
                return v
    return []


def fetch(days_back, prev):
    from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator, resolve_api_key

    key = os.getenv("GARMIN_PERSONAL_API_KEY") or resolve_api_key()
    with PersonalApiAuthenticator() as auth:
        token = auth.obtain_token(key, force_refresh=bool(os.getenv("CI")))

    today = dt.date.today()
    start = today - dt.timedelta(days=days_back)
    by_date = {d["date"]: d for d in prev.get("days", [])}
    print("Fetching %s .. %s" % (start, today))

    with GarminPersonalApiClient(token.access_token) as c:
        sums, sleeps, hrvs = {}, {}, {}
        for a, b in chunks(start, today, 365):
            for s in as_list(call(c.get_daily_summaries, a, b), "data"):
                sums[s.get("calendarDate")] = s
        for a, b in chunks(start, today, 31):
            for s in as_list(call(c.get_daily_sleep_summaries, a, b)):
                if isinstance(s, dict) and s.get("calendarDate"):
                    sleeps[s["calendarDate"]] = s
            time.sleep(0.3)
        for a, b in chunks(start, today, 60):
            for h in as_list(call(c.get_daily_hrv_summaries, a, b), "hrvSummaries"):
                if isinstance(h, dict) and h.get("calendarDate"):
                    hrvs[h["calendarDate"]] = h
            time.sleep(0.3)
        print("  summaries %d, sleep %d, hrv %d" % (len(sums), len(sleeps), len(hrvs)))

        for k in sorted(set(sums) | set(sleeps) | set(hrvs)):
            day = norm_summary(sums.get(k) or {"calendarDate": k})
            day["date"] = k
            day["sleep"] = norm_sleep(sleeps.get(k), day.pop("_sleepBB", None))
            day["hrv"] = norm_hrv(hrvs.get(k))
            day["readiness"] = None
            day["vo2"] = None
            by_date[k] = day

        # intraday detail for today
        t = iso(today)
        hr = call(c.get_daily_heart_rate, t) or {}
        bb = as_list(call(c.get_daily_body_battery, t, t, chunks=144))
        bb_vals = g(bb, 0, "bodyBatteryValuesArray", default=[]) if bb else []
        hrv_day = call(c.get_daily_hrv, t) or {}
        hrv_night = []
        for r in hrv_day.get("hrvReadings") or []:
            if r.get("hrvValue") and r.get("readingTimeLocal"):
                hrv_night.append([r["readingTimeLocal"][:16], r["hrvValue"]])
        intraday = {
            "date": t,
            "hr": minute_series(hr.get("heartRateValues"), step=4),
            "bb": minute_series(bb_vals, step=10),
            "hrvNight": hrv_night,
            "lastSevenRhr": hr.get("lastSevenDaysAvgRestingHeartRate"),
        }

        acts = []
        for page in range(0, MAX_ACTIVITIES, 100):
            batch = as_list(call(c.search_activities, start=page, limit=min(100, MAX_ACTIVITIES - page)))
            acts += batch
            if len(batch) < 100:
                break
        activities = [norm_activity(a) for a in acts if isinstance(a, dict)]

        fa = call(c.get_fitness_age, t) or {}
        fitness = None
        if fa.get("fitnessAge"):
            fitness = {
                "age": round(fa["fitnessAge"], 1),
                "chrono": fa.get("chronologicalAge"),
                "achievable": round(fa["achievableFitnessAge"], 1) if fa.get("achievableFitnessAge") else None,
                "vigorousDays": g(fa, "components", "vigorousDaysAvg", "value"),
                "vigorousDaysTarget": g(fa, "components", "vigorousDaysAvg", "targetValue"),
                "vigorousMin": g(fa, "components", "vigorousMinutesAvg", "value"),
                "vigorousMinTarget": g(fa, "components", "vigorousMinutesAvg", "targetValue"),
                "bmi": g(fa, "components", "bmi", "value"),
            }

    name = (acts[0].get("ownerFullName") if acts else None) or g(prev, "profile", "name")
    return by_date, intraday, activities, {"name": name, "device": "fēnix 8 Pro"}, fitness


# ---------------------------------------------------------------- sample
def sample():
    rnd = random.Random(42)
    today = dt.date.today()
    days = []
    vo2 = 49.0
    hrv_base = 58
    for i in range(365, -1, -1):
        date = today - dt.timedelta(days=i)
        season = math.sin((date.timetuple().tm_yday / 365) * 2 * math.pi)
        fitness = (365 - i) / 365  # slowly improving over the year
        weekend = date.weekday() >= 5
        bad = rnd.random() < 0.08  # occasional rough night
        total = int(rnd.gauss(7.3 if weekend else 6.9, 0.55) * 3600) - (5400 if bad else 0)
        deep = int(total * rnd.uniform(0.14, 0.22))
        rem = int(total * rnd.uniform(0.18, 0.26))
        awake = int(rnd.uniform(600, 2400) + (1800 if bad else 0))
        light = total - deep - rem
        score = max(35, min(98, int(50 + (total / 3600 - 5) * 12 + deep / total * 60 - awake / 600 + rnd.gauss(0, 4))))
        hrv_night = max(30, int(hrv_base + fitness * 6 + season * 3 - (14 if bad else 0) + rnd.gauss(0, 6)))
        rhr = int(round(52 - fitness * 3 - season * 1.5 + (4 if bad else 0) + rnd.gauss(0, 1.4)))
        steps = max(1500, int(rnd.gauss(12500 if weekend else 9800, 3200)))
        vo2 += rnd.gauss(0.012, 0.05)
        start = dt.datetime.combine(date - dt.timedelta(days=1), dt.time(23, 0)) + dt.timedelta(minutes=rnd.randint(-50, 60))
        end = start + dt.timedelta(seconds=total + awake)
        stress = max(12, min(70, int(rnd.gauss(30, 8) + (12 if bad else 0))))
        bb_high = max(30, min(100, int(score * 0.85 + rnd.gauss(8, 6))))
        ready = max(5, min(100, int(score * 0.45 + (hrv_night - 45) * 1.2 + rnd.gauss(10, 8))))
        days.append({
            "date": iso(date),
            "steps": steps if i else int(steps * 0.62),
            "stepGoal": 10000,
            "distance": int(steps * 0.78),
            "activeKcal": int(steps * 0.045 + rnd.uniform(100, 600)),
            "totalKcal": int(1900 + steps * 0.045 + rnd.uniform(100, 600)),
            "rhr": rhr, "minHr": rhr - 4, "maxHr": int(rnd.uniform(120, 178)),
            "stress": stress,
            "bbHigh": bb_high, "bbLow": max(5, bb_high - int(rnd.uniform(40, 75))),
            "bbCharged": int(rnd.uniform(40, 80)), "bbDrained": int(rnd.uniform(45, 85)),
            "intensity": int(max(0, rnd.gauss(45, 30))),
            "floors": int(rnd.uniform(4, 25)),
            "spo2": int(rnd.uniform(94, 98)), "resp": round(rnd.uniform(13, 16), 1),
            "sleep": {
                "score": score, "total": total, "deep": deep, "light": light, "rem": rem, "awake": awake,
                "start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds"),
                "resp": round(rnd.uniform(12.5, 15), 1), "spo2": int(rnd.uniform(93, 97)),
                "stress": int(rnd.uniform(8, 25)), "bbChange": int(score * 0.7 + rnd.gauss(0, 6)),
                "need": 8 * 3600 if not bad else int(8.5 * 3600),
            },
            "hrv": {"night": hrv_night, "weekly": None, "status": None, "low": 50, "high": 72},
            "readiness": {"score": ready, "level": "HIGH" if ready >= 75 else "MODERATE" if ready >= 50 else "LOW"},
            "vo2": round(vo2, 1),
        })
    for idx, d in enumerate(days):
        win = [x["hrv"]["night"] for x in days[max(0, idx - 6): idx + 1]]
        w = round(sum(win) / len(win))
        d["hrv"]["weekly"] = w
        d["hrv"]["status"] = "BALANCED" if 50 <= w <= 72 else ("UNBALANCED" if w > 40 else "LOW")
    # make "today" a well-recovered day so the sample briefing matches the numbers
    days[-1]["hrv"]["night"] = 64
    days[-1]["rhr"] = 48

    # intraday for today
    hr, bb, st = [], [], []
    level = days[-2]["bbLow"] + days[-1]["sleep"]["bbChange"]
    level = max(20, min(100, level))
    now_min = 15 * 60 + 40
    for m in range(0, now_min, 5):
        asleep = m < 6 * 60 + 50
        base = 50 if asleep else 72
        if 7 * 60 + 10 <= m <= 8 * 60:  # morning run
            base = 152 + 10 * math.sin((m - 430) / 8)
        hr.append([m, int(base + rnd.gauss(0, 3 if asleep else 6))])
        if asleep:
            level = min(100, level + 0.55)
        else:
            level = max(5, level - (1.6 if 430 <= m <= 480 else 0.22))
        bb.append([m, int(level)])
        if not asleep and not (430 <= m <= 480):
            st.append([m, max(5, int(rnd.gauss(30, 14)))])
    last = days[-1]["sleep"]
    s = dt.datetime.fromisoformat(last["start"])
    hyp, t = [], s
    cycle = [(1, 25), (0, 40), (1, 20), (2, 18), (1, 30), (0, 25), (2, 25), (3, 4), (1, 35), (0, 12), (2, 30), (1, 30), (2, 35), (3, 6), (1, 20)]
    for stage, mins in cycle:
        e = t + dt.timedelta(minutes=mins)
        hyp.append([t.isoformat(timespec="minutes"), e.isoformat(timespec="minutes"), stage])
        t = e
    intraday = {"date": iso(today), "hr": hr, "bb": bb, "stress": st, "hypnogram": hyp}

    types = [("running", "Morning Run", 0.45), ("cycling", "Road Ride", 0.2), ("strength_training", "Strength", 0.15),
             ("hiking", "Hike", 0.08), ("lap_swimming", "Pool Swim", 0.07), ("trail_running", "Trail Run", 0.05)]
    acts = []
    d = dt.datetime.combine(today, dt.time(7, 10))
    aid = 18000000000
    while len(acts) < 120:
        r = rnd.random()
        acc = 0
        for key, name, p in types:
            acc += p
            if r <= acc:
                break
        dur = {"running": rnd.uniform(1800, 4200), "cycling": rnd.uniform(3600, 9000), "strength_training": rnd.uniform(2400, 3600),
               "hiking": rnd.uniform(7200, 14400), "lap_swimming": rnd.uniform(1800, 3000), "trail_running": rnd.uniform(3000, 6000)}[key]
        spd = {"running": rnd.uniform(2.8, 3.5), "cycling": rnd.uniform(7, 9.5), "strength_training": 0,
               "hiking": rnd.uniform(1.1, 1.5), "lap_swimming": rnd.uniform(0.6, 0.8), "trail_running": rnd.uniform(2.3, 2.9)}[key]
        avg = int(rnd.uniform(118, 162))
        z = [rnd.uniform(0, 1) for _ in range(5)]
        if key in ("running", "trail_running"):
            z = [0.05, 0.2, 0.4, 0.25, 0.1]
        zs = sum(z)
        acts.append({
            "id": aid, "name": name, "type": key, "start": d.isoformat(timespec="seconds"),
            "duration": int(dur), "distance": int(dur * spd), "avgHr": avg, "maxHr": avg + int(rnd.uniform(12, 28)),
            "kcal": int(dur / 60 * rnd.uniform(8, 13)), "elevation": int(rnd.uniform(10, 900) if key != "lap_swimming" else 0),
            "avgSpeed": round(spd, 3), "teAer": round(rnd.uniform(2.0, 4.6), 1), "teAna": round(rnd.uniform(0, 3.2), 1),
            "load": int(rnd.uniform(40, 260)), "zones": [int(dur * x / zs) for x in z],
        })
        aid += 1
        d = dt.datetime.combine((d - dt.timedelta(days=rnd.choice([1, 1, 1, 2, 2, 3]))).date(), dt.time(rnd.choice([6, 7, 7, 12, 17, 18]), rnd.randint(0, 59)))
    fitness = {"age": 27.9, "chrono": 32, "achievable": 25.7, "vigorousDays": 0.6, "vigorousDaysTarget": 3,
               "vigorousMin": 25.3, "vigorousMinTarget": 75, "bmi": 20.4}
    for d in days:
        d["vo2"] = None
        d["readiness"] = None
    add_recovery(days)
    intraday["hrvNight"] = [[(dt.datetime.combine(today, dt.time(0)) + dt.timedelta(minutes=m)).isoformat(timespec="minutes")[:16],
                             int(55 + 12 * math.sin(m / 70) + rnd.gauss(0, 5))] for m in range(-60, 380, 5)]
    return {d["date"]: d for d in days}, intraday, acts, {"name": "Alex", "device": "fēnix 8 Pro"}, fitness


# ---------------------------------------------------------------- AI insights
AI_PROMPT = """You are a sharp, encouraging health coach reading someone's Garmin data.
Write today's briefing based on the JSON below (last 14 days in detail plus 90-day and 365-day averages).
Rules: be specific with numbers, compare to their own baselines, no medical diagnoses, no generic advice.
Write durations like "4h 43m" (never decimal hours). "recovery_pct" is the app's Recovery score (0-100%, from HRV, resting HR and sleep vs baseline); call it Recovery. Keep the body under 70 words.
Return ONLY JSON: {"headline": "<max 8 words>", "body": "<2-3 sentences>", "tips": ["<short actionable tip>", "<tip>", "<tip>"]}"""


def ai_insights(days, activities):
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")):
        return None

    def avg(rows, f):
        v = [f(r) for r in rows]
        v = [x for x in v if x is not None]
        return round(sum(v) / len(v), 1) if v else None

    def summ(rows):
        return {
            "sleep_h": avg(rows, lambda d: (g(d, "sleep", "total") or 0) / 3600 or None),
            "sleep_score": avg(rows, lambda d: g(d, "sleep", "score")),
            "hrv": avg(rows, lambda d: g(d, "hrv", "night")),
            "rhr": avg(rows, lambda d: d.get("rhr")),
            "steps": avg(rows, lambda d: d.get("steps")),
            "stress": avg(rows, lambda d: d.get("stress")),
        }

    payload = {
        "last14": [
            {k: d.get(k) for k in ("date", "steps", "rhr", "stress", "bbHigh", "intensity")}
            | {"sleep_h": round((g(d, "sleep", "total") or 0) / 3600, 2), "sleep_score": g(d, "sleep", "score"),
               "deep_h": round((g(d, "sleep", "deep") or 0) / 3600, 2), "hrv": g(d, "hrv", "night"),
               "recovery_pct": g(d, "readiness", "score")}
            for d in days[-14:]
        ],
        "avg90": summ(days[-90:]),
        "avg365": summ(days[-365:]),
        "recent_activities": [
            {k: a.get(k) for k in ("start", "type", "duration", "distance", "avgHr", "load", "teAer")} for a in activities[:10]
        ],
    }
    prompt = AI_PROMPT + "\n\n" + json.dumps(payload)
    for name, fn in (("Gemini", ask_gemini), ("Claude", ask_claude)):
        try:
            text = fn(prompt)
        except Exception as e:  # noqa: BLE001
            print("  ! %s briefing failed: %s" % (name, str(e)[:300]), file=sys.stderr)
            continue
        if not text:
            continue
        try:
            out = json.loads(text[text.find("{"): text.rfind("}") + 1])
        except ValueError:
            print("  ! %s returned non-JSON: %s" % (name, text[:200]), file=sys.stderr)
            continue
        out["generated"] = dt.datetime.now().astimezone().isoformat(timespec="minutes")
        out["model"] = name
        print("  AI briefing written by %s: %s" % (name, out.get("headline")))
        return out
    return None


def http_json(url, body=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s %s" % (e.code, e.read().decode(errors="replace")[:300]))


def gemini_candidates(key):
    """GEMINI_MODEL if set, else stable 'flash' models newest first (the newest are often overloaded,
    so the caller falls back down the list)."""
    if os.getenv("GEMINI_MODEL"):
        return [os.getenv("GEMINI_MODEL")]
    import re as _re
    models = http_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                       headers={"x-goog-api-key": key}, timeout=30).get("models", [])
    names = [m["name"].split("/", 1)[1] for m in models if "generateContent" in m.get("supportedGenerationMethods", [])]
    bad = ("preview", "exp", "image", "tts", "live", "audio", "embedding", "transcribe", "omni", "robotics", "computer", "latest", "nano")
    out = []
    for n in names:
        v = _re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash(-lite)?", n)
        if v and not any(x in n for x in bad):
            out.append((0 if v.group(2) else 1, float(v.group(1)), n))
    ranked = [n for _, _, n in sorted(out, reverse=True)]
    full = [n for n in ranked if not n.endswith("-lite")][:4]
    lite = [n for n in ranked if n.endswith("-lite")][:2]
    return (full + lite) or ["gemini-flash-latest"]


def ask_gemini(prompt):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6, "maxOutputTokens": 4096}}
    models = gemini_candidates(key)
    for attempt in range(2):
      if attempt:
          print("  All Gemini models busy, waiting 45s and retrying")
          time.sleep(45)
      for model in models:
        t0 = time.time()
        try:
            r = http_json("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model,
                          body, headers={"x-goog-api-key": key}, timeout=60)
        except Exception as e:  # noqa: BLE001 - 503 overloaded, 429 quota, timeouts: try the next model
            msg = " ".join(str(e).split())
            print("  Gemini %s unavailable after %.0fs (%s), trying next" % (model, time.time() - t0, msg[:140]))
            if "HTTP 404" in msg:
                models = [m for m in models if m != model]
            continue
        parts = g(r, "candidates", 0, "content", "parts", default=[]) or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if text.strip():
            print("  Gemini model used: %s (%.0fs)" % (model, time.time() - t0))
            return text
        print("  Gemini %s returned no text (%s), trying next" % (model, g(r, "candidates", 0, "finishReason")))
    return None


def ask_claude(prompt):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    r = http_json("https://api.anthropic.com/v1/messages",
                  {"model": os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 600,
                   "messages": [{"role": "user", "content": prompt}]},
                  headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    return g(r, "content", 0, "text")


# ---------------------------------------------------------------- main
def load_previous():
    url = os.getenv("PREVIOUS_DATA_URL")
    if url:
        try:
            with urllib.request.urlopen(url + "?t=%d" % time.time(), timeout=30) as r:
                prev = json.load(r)
            if prev.get("source") == "garmin":
                print("Loaded previous data: %d days" % len(prev.get("days", [])))
                return prev
        except Exception as e:  # noqa: BLE001
            print("No previous data (%s)" % e)
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
            if prev.get("source") == "garmin":
                return prev
        except Exception:  # noqa: BLE001
            pass
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--backfill", type=int, default=None)
    args = ap.parse_args()

    if args.sample:
        by_date, intraday, acts, profile, fitness = sample()
        prev = {}
        source = "sample"
    else:
        prev = load_previous()
        n = args.backfill or (10 if prev.get("days") else 364)
        by_date, intraday, acts, profile, fitness = fetch(n, prev)
        source = "garmin"

    cutoff = iso(dt.date.today() - dt.timedelta(days=HISTORY_DAYS))
    days = [by_date[k] for k in sorted(by_date) if k >= cutoff]
    add_recovery(days)
    insights = None if args.sample else ai_insights(days, acts)
    if insights is None and prev.get("insights"):
        insights = prev["insights"]
    if args.sample:
        insights = {
            "headline": "Recovered and ready to push",
            "body": "Your HRV of 64 ms sits at the top of your 7-day range and resting HR is 2 bpm under your 90-day average. "
                    "Sleep was 7h 12m with solid deep sleep, so today is a good day for intensity.",
            "tips": ["Schedule your hardest session of the week today", "Aim for lights out by 23:00 to protect the trend",
                     "Steps are 18% below your weekday average, add a walk after lunch"],
            "generated": dt.datetime.now().isoformat(timespec="minutes"),
        }

    data = {
        "generated": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
        "source": source,
        "profile": profile,
        "days": days,
        "today": intraday,
        "activities": acts,
        "fitness": fitness or prev.get("fitness"),
        "insights": insights,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    print("Wrote %s (%d days, %d activities, %.0f KB)" % (OUT, len(days), len(acts), OUT.stat().st_size / 1024))


if __name__ == "__main__":
    main()
