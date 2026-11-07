"""Deterministic sports & health analysis.

Turns raw daily data + activities into a compact set of *facts* (numbers with context) that the
coach model narrates. All maths lives here so the model never has to calculate, only interpret.

Frameworks used (see coach_skill.md for how they are interpreted):
- HRV: last night vs 28-day baseline (z-score), 7-day rolling mean vs Garmin's balanced band,
  7-day coefficient of variation (Plews et al.: falling mean + rising CV = accumulating fatigue).
- Resting HR: deviation vs 28-day baseline, consecutive elevated days.
- Sleep: duration vs need, 7-day sleep debt, regularity (SD of bed/wake time), social jet lag
  (weekend vs weekday midpoint), stage proportions vs typical adult ranges.
- Training load: acute (7d) vs chronic (28d) load ratio (ACWR, Gabbett), Foster monotony & strain,
  intensity distribution from HR zones (polarised / pyramidal / threshold-heavy), days since rest.
- Daily activity: steps vs baseline, sedentary days, WHO 150 min/week intensity target.
- Cross-metric relationships over 90 days (Pearson r, only reported when n is large enough).
- Vitals Age (Garmin fitness age) trend -> pace of aging (biological years per calendar year).
"""
import datetime as dt
import math
from statistics import mean, pstdev


def _vals(xs):
    return [x for x in xs if x is not None]


def avg(xs):
    v = _vals(xs)
    return mean(v) if v else None


def sd(xs):
    v = _vals(xs)
    return pstdev(v) if len(v) > 1 else None


def rnd(x, n=1):
    return None if x is None else round(x, n)


def pearson(pairs, min_n=20):
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    if len(pairs) < min_n:
        return None
    xs, ys = zip(*pairs)
    mx, my = mean(xs), mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return round(sum((x - mx) * (y - my) for x, y in pairs) / (sx * sy), 2), len(pairs)


def slope_per_week(values):
    """Least-squares slope of a daily series, in units per week."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 7:
        return None
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    den = sum((p[0] - mx) ** 2 for p in pts)
    return None if not den else sum((p[0] - mx) * (p[1] - my) for p in pts) / den * 7


def _clock_minutes(iso, pivot=18 * 60):
    """Minutes after `pivot` (default 18:00) so bedtimes around midnight stay continuous."""
    if not iso:
        return None
    t = dt.datetime.fromisoformat(iso[:19])
    m = t.hour * 60 + t.minute - pivot
    return m + 1440 if m < 0 else m


def _hhmm(minutes_after_18):
    if minutes_after_18 is None:
        return None
    m = int(round(minutes_after_18 + 18 * 60)) % 1440
    return "%02d:%02d" % (m // 60, m % 60)


def g(d, *path):
    for p in path:
        if d is None:
            return None
        d = d.get(p) if isinstance(d, dict) else None
    return d


def analyse(days, activities, fitness=None):
    """Return a dict of facts. `days` sorted oldest->newest; the last item is today (may be partial)."""
    if not days:
        return {}
    today = days[-1]
    hist = days[:-1]
    d7, d28, d90 = hist[-7:], hist[-28:], hist[-90:]
    f = {"date": today.get("date")}

    # ---------------------------------------------------------------- HRV
    hrv_now = g(today, "hrv", "night")
    h28 = [g(d, "hrv", "night") for d in d28]
    h7 = [g(d, "hrv", "night") for d in d7] + [hrv_now]
    m28, s28 = avg(h28), sd(h28)
    m7, s7 = avg(h7), sd(h7)
    f["hrv"] = {
        "last_night_ms": hrv_now,
        "baseline_28d_ms": rnd(m28),
        "z_vs_28d": rnd((hrv_now - m28) / s28, 2) if hrv_now and m28 and s28 else None,
        "avg_7d_ms": rnd(m7),
        "cv_7d_pct": rnd(s7 / m7 * 100) if m7 and s7 else None,
        "cv_28d_pct": rnd(s28 / m28 * 100) if m28 and s28 else None,
        "garmin_status": g(today, "hrv", "status"),
        "balanced_range_ms": [g(today, "hrv", "low"), g(today, "hrv", "high")],
        "trend_ms_per_week_28d": rnd(slope_per_week(h28 + [hrv_now]), 2),
        "avg_90d_ms": rnd(avg([g(d, "hrv", "night") for d in d90])),
    }

    # ---------------------------------------------------------------- resting HR
    r28 = [d.get("rhr") for d in d28]
    rm = avg(r28)
    elevated = 0
    for d in reversed(hist[-14:] + [today]):
        if d.get("rhr") is not None and rm is not None and d["rhr"] >= rm + 3:
            elevated += 1
        else:
            break
    f["resting_hr"] = {
        "today_bpm": today.get("rhr"),
        "baseline_28d_bpm": rnd(rm),
        "delta_bpm": rnd(today["rhr"] - rm) if today.get("rhr") is not None and rm else None,
        "consecutive_elevated_days": elevated,
        "trend_bpm_per_week_28d": rnd(slope_per_week(r28 + [today.get("rhr")]), 2),
        "avg_90d_bpm": rnd(avg([d.get("rhr") for d in d90])),
        "lowest_90d_bpm": min(_vals([d.get("rhr") for d in d90]), default=None),
    }

    # ---------------------------------------------------------------- sleep
    def sl(d, k):
        return g(d, "sleep", k)

    last = today.get("sleep") or {}
    nights7 = d7[-6:] + [today]
    need = avg([sl(d, "need") for d in nights7]) or 8 * 3600
    dur7 = [sl(d, "total") for d in nights7]
    beds = [_clock_minutes(sl(d, "start")) for d in hist[-14:] + [today]]
    wakes = [_clock_minutes(sl(d, "end")) for d in hist[-14:] + [today]]
    mids = [((b + w) / 2 if b is not None and w is not None else None) for b, w in zip(beds, wakes)]
    wk_days = hist[-28:] + [today]

    def is_weekend_night(d):  # sleep attributed to the wake-up date: Sat/Sun mornings
        return dt.date.fromisoformat(d["date"]).weekday() >= 5

    mid_we = avg([((_clock_minutes(sl(d, "start")) or 0) + (_clock_minutes(sl(d, "end")) or 0)) / 2
                  for d in wk_days if is_weekend_night(d) and sl(d, "start")])
    mid_wd = avg([((_clock_minutes(sl(d, "start")) or 0) + (_clock_minutes(sl(d, "end")) or 0)) / 2
                  for d in wk_days if not is_weekend_night(d) and sl(d, "start")])
    tot = last.get("total") or 0
    f["sleep"] = {
        "last_night": {
            "duration_min": round(tot / 60) if tot else None,
            "score": last.get("score"),
            "garmin_feedback": last.get("feedback"),
            "bedtime": (last.get("start") or "")[11:16] or None,
            "wake": (last.get("end") or "")[11:16] or None,
            "deep_pct": round(last["deep"] / tot * 100) if tot and last.get("deep") is not None else None,
            "rem_pct": round(last["rem"] / tot * 100) if tot and last.get("rem") is not None else None,
            "awake_min": round((last.get("awake") or 0) / 60),
            "sleeping_hr": last.get("avgHr"),
            "respiration": last.get("resp"),
            "body_battery_gain": last.get("bbChange"),
        },
        "need_min": round(need / 60),
        "avg_7d_min": round(avg(dur7) / 60) if avg(dur7) else None,
        "avg_90d_min": round(avg([sl(d, "total") for d in d90]) / 60) if avg([sl(d, "total") for d in d90]) else None,
        "debt_7d_min": round(sum(need - x for x in _vals(dur7)) / 60) if _vals(dur7) else None,
        "nights_under_6h_14d": sum(1 for d in hist[-13:] + [today] if (sl(d, "total") or 1e9) < 6 * 3600),
        "avg_score_7d": rnd(avg([sl(d, "score") for d in nights7]), 0),
        "avg_score_90d": rnd(avg([sl(d, "score") for d in d90]), 0),
        "bedtime_avg_14d": _hhmm(avg(beds)),
        "bedtime_sd_min_14d": rnd(sd(beds), 0),
        "wake_avg_14d": _hhmm(avg(wakes)),
        "wake_sd_min_14d": rnd(sd(wakes), 0),
        "midpoint_sd_min_14d": rnd(sd(mids), 0),
        "social_jetlag_min": rnd(mid_we - mid_wd, 0) if mid_we is not None and mid_wd is not None else None,
        "deep_pct_avg_28d": rnd(avg([sl(d, "deep") / sl(d, "total") * 100 for d in d28 if sl(d, "total")]), 0),
        "rem_pct_avg_28d": rnd(avg([sl(d, "rem") / sl(d, "total") * 100 for d in d28 if sl(d, "total")]), 0),
        "late_bedtimes_after_1am_14d": sum(1 for b in beds if b is not None and b > 7 * 60),
    }

    # ---------------------------------------------------------------- training load
    by_day = {}
    zone_tot = [0.0] * 5
    sport_min = {}
    late_days = set()
    for a in activities:
        start = (a.get("start") or "")[:10]
        if not start:
            continue
        by_day[start] = by_day.get(start, 0) + (a.get("load") or 0)
        if a.get("start", "")[11:13] and int(a["start"][11:13]) >= 19:
            late_days.add(start)
    end = dt.date.fromisoformat(today["date"])
    daily = [by_day.get((end - dt.timedelta(days=i)).isoformat(), 0) for i in range(27, -1, -1)]
    acute, chronic = sum(daily[-7:]), sum(daily) / 4
    m7l, s7l = mean(daily[-7:]), pstdev(daily[-7:])
    monotony = (m7l / s7l) if s7l else None
    for a in activities:
        if a.get("start", "")[:10] >= (end - dt.timedelta(days=27)).isoformat():
            for i, z in enumerate(a.get("zones") or []):
                zone_tot[i] += z or 0
            k = a.get("type") or "other"
            sport_min[k] = sport_min.get(k, 0) + (a.get("duration") or 0) / 60
    zsum = sum(zone_tot)
    low, mid, high = ((zone_tot[0] + zone_tot[1]) / zsum, zone_tot[2] / zsum, (zone_tot[3] + zone_tot[4]) / zsum) if zsum else (None,) * 3
    if zsum:
        dist = "polarised" if low >= 0.7 and high > mid else "pyramidal" if low >= mid >= high else "threshold-heavy" if mid >= max(low, high) * 0.8 else "high-intensity-heavy" if high > 0.3 else "mixed"
    else:
        dist = None
    rest = 0
    for v in reversed(daily):
        if v == 0:
            break
        rest += 1
    recent = [a for a in activities if a.get("start", "")[:10] >= (end - dt.timedelta(days=6)).isoformat()]
    f["training"] = {
        "load_7d": round(acute),
        "load_28d_weekly_avg": round(chronic),
        "acwr": rnd(acute / chronic, 2) if chronic else None,
        "monotony_7d": rnd(monotony, 2),
        "strain_7d": round(acute * monotony) if monotony else None,
        "sessions_7d": len(recent),
        "sessions_28d": sum(1 for a in activities if a.get("start", "")[:10] >= (end - dt.timedelta(days=27)).isoformat()),
        "consecutive_training_days": rest,
        "intensity_distribution_28d": {"z1_2_pct": rnd(low * 100 if low is not None else None, 0),
                                       "z3_pct": rnd(mid * 100 if mid is not None else None, 0),
                                       "z4_5_pct": rnd(high * 100 if high is not None else None, 0),
                                       "model": dist},
        "minutes_by_sport_28d": {k: round(v) for k, v in sorted(sport_min.items(), key=lambda x: -x[1])},
        "recent_sessions": [{"date": a.get("start", "")[:16], "type": a.get("type"), "min": round((a.get("duration") or 0) / 60),
                             "km": rnd((a.get("distance") or 0) / 1000), "avg_hr": a.get("avgHr"), "load": a.get("load"),
                             "te_aerobic": a.get("teAer"), "te_label": a.get("teLabel")} for a in recent[:8]],
    }

    # ---------------------------------------------------------------- daily activity
    st7 = [d.get("steps") for d in d7]
    st28 = [d.get("steps") for d in d28]
    f["daily_activity"] = {
        "steps_today_so_far": today.get("steps"),
        "steps_avg_7d": rnd(avg(st7), 0),
        "steps_avg_28d": rnd(avg(st28), 0),
        "steps_goal": today.get("stepGoal"),
        "sedentary_days_under_5k_7d": sum(1 for s in st7 if s is not None and s < 5000),
        "intensity_min_7d": sum(d.get("intensity") or 0 for d in d7),
        "who_target_min_week": 150,
        "stress_avg_7d": rnd(avg([d.get("stress") for d in d7]), 0),
        "stress_avg_28d": rnd(avg([d.get("stress") for d in d28]), 0),
        "body_battery_peak_7d": rnd(avg([d.get("bbHigh") for d in d7]), 0),
    }

    # ---------------------------------------------------------------- recovery (computed score)
    f["recovery"] = {
        "today_pct": g(today, "readiness", "score"),
        "avg_7d_pct": rnd(avg([g(d, "readiness", "score") for d in d7]), 0),
        "avg_28d_pct": rnd(avg([g(d, "readiness", "score") for d in d28]), 0),
    }

    # ---------------------------------------------------------------- relationships (90 days)
    idx = {d["date"]: d for d in days}

    def nxt(d):
        return idx.get((dt.date.fromisoformat(d["date"]) + dt.timedelta(days=1)).isoformat())

    rel = {}
    r = pearson([(sl(d, "total"), g(nxt(d), "hrv", "night")) for d in d90 if nxt(d)])
    if r:
        rel["sleep_duration_vs_next_night_hrv"] = {"r": r[0], "n": r[1]}
    r = pearson([(by_day.get(d["date"], 0), g(nxt(d), "readiness", "score")) for d in d90 if nxt(d)])
    if r:
        rel["training_load_vs_next_day_recovery"] = {"r": r[0], "n": r[1]}
    r = pearson([(d.get("stress"), sl(nxt(d), "score")) for d in d90 if nxt(d)])
    if r:
        rel["day_stress_vs_that_nights_sleep_score"] = {"r": r[0], "n": r[1]}
    late_scores = [sl(nxt(d), "score") for d in d90 if nxt(d) and d["date"] in late_days]
    other_scores = [sl(nxt(d), "score") for d in d90 if nxt(d) and d["date"] not in late_days and d["date"] in by_day]
    if len(_vals(late_scores)) >= 4 and len(_vals(other_scores)) >= 4:
        rel["sleep_score_after_evening_workouts_vs_earlier"] = {"evening": rnd(avg(late_scores), 0), "earlier": rnd(avg(other_scores), 0),
                                                                "n_evening": len(_vals(late_scores))}
    f["relationships_90d"] = rel

    # ---------------------------------------------------------------- 30d vs previous 30d
    def window(a, b):
        return days[-a - 1:-b - 1] if b else days[-a - 1:-1]

    cur, prev = window(30, 0), window(60, 30)
    comp = {}
    for name, fn in (("sleep_min", lambda d: (sl(d, "total") or 0) / 60 or None), ("sleep_score", lambda d: sl(d, "score")),
                     ("hrv", lambda d: g(d, "hrv", "night")), ("rhr", lambda d: d.get("rhr")), ("steps", lambda d: d.get("steps")),
                     ("stress", lambda d: d.get("stress")), ("recovery", lambda d: g(d, "readiness", "score"))):
        a, b = avg([fn(d) for d in cur]), avg([fn(d) for d in prev])
        comp[name] = {"last_30d": rnd(a), "prev_30d": rnd(b), "change_pct": rnd((a - b) / b * 100, 0) if a and b else None}
    f["last_30d_vs_prev_30d"] = comp

    # ---------------------------------------------------------------- vitals age
    if fitness:
        f["vitals_age"] = {k: fitness.get(k) for k in ("age", "chrono", "achievable", "pace", "pace_window_days",
                                                         "vigorousDays", "vigorousDaysTarget", "vigorousMin", "vigorousMinTarget", "bmi")}
        hist_pts = fitness.get("history") or []
        if len(hist_pts) >= 2:
            f["vitals_age"]["age_12_months_ago"] = hist_pts[0][1]

    # ---------------------------------------------------------------- flags (priority signals)
    flags = []
    z = f["hrv"]["z_vs_28d"]
    if z is not None and z <= -1:
        flags.append("HRV well below baseline (z %.1f)" % z)
    if f["hrv"]["cv_7d_pct"] and f["hrv"]["cv_28d_pct"] and f["hrv"]["cv_7d_pct"] > f["hrv"]["cv_28d_pct"] * 1.5:
        flags.append("HRV day-to-day variability rising")
    if elevated >= 2:
        flags.append("resting HR elevated %d days in a row" % elevated)
    if f["sleep"]["debt_7d_min"] and f["sleep"]["debt_7d_min"] > 180:
        flags.append("sleep debt %d min this week" % f["sleep"]["debt_7d_min"])
    if f["sleep"]["bedtime_sd_min_14d"] and f["sleep"]["bedtime_sd_min_14d"] > 60:
        flags.append("irregular bedtime (SD %d min)" % f["sleep"]["bedtime_sd_min_14d"])
    acwr = f["training"]["acwr"]
    if acwr is not None and acwr > 1.5:
        flags.append("training load spike (ACWR %.2f)" % acwr)
    if acwr is not None and acwr < 0.6 and chronic > 0:
        flags.append("training load dropping (ACWR %.2f)" % acwr)
    if monotony and monotony > 2:
        flags.append("high training monotony (%.1f)" % monotony)
    if fitness and fitness.get("pace") and fitness["pace"] > 1.5:
        flags.append("Vitals Age rising faster than calendar age (pace %.1fx)" % fitness["pace"])
    f["priority_flags"] = flags
    return f


def fitness_pace(history, window_days=183):
    """Biological years gained per calendar year over the last `window_days`, by least squares."""
    if not history:
        return None
    end = dt.date.fromisoformat(history[-1][0])
    pts = [((dt.date.fromisoformat(d) - end).days / 365.25, a) for d, a in history
           if a is not None and (end - dt.date.fromisoformat(d)).days <= window_days]
    if len(pts) < 3:
        return None
    mx = mean(p[0] for p in pts)
    my = mean(p[1] for p in pts)
    den = sum((p[0] - mx) ** 2 for p in pts)
    return None if not den else round(sum((p[0] - mx) * (p[1] - my) for p in pts) / den, 2)
