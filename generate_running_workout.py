#!/usr/bin/env python3
"""
generate_running_workout.py — Genereert een gepersonaliseerd 2x/week
hardloopschema via Claude en pusht dit naar intervals.icu.

Standaard schema: dinsdag 20:00 (snelheidswerk) + zaterdag 09:00 (lange duurloop).
De loopdag kan worden verschoven via health_input.json in de Gist:
  "run_1": "2026-04-22T20:00"   — overschrijft dinsdag-sessie (datum+tijd)
  "run_2": "2026-04-26T09:00"   — overschrijft zaterdag-sessie (datum+tijd)

Doel: 5K verbeteren van 28 min naar 26 min. Geen einddatum — continu programma.
Workouts hebben Runna-stijl: specifieke pacedoelen per stap, gestructureerde
herhalingen, walking rest. workout_doc zorgt voor grafiek in intervals.icu
en gestructureerde workout op de Garmin Fenix.

GitHub Secrets vereist:
  INTERVALS_ATHLETE_ID  — intervals.icu athlete ID (bijv. "i12345")
  INTERVALS_API_KEY     — intervals.icu API key
  ANTHROPIC_API_KEY     — Claude API key
  GIST_ID               — GitHub Gist ID
  GITHUB_TOKEN          — GitHub token met gist scope (gebruik GIST_TOKEN secret)
  VAPID_PRIVATE_KEY     — VAPID private key voor Web Push notificaties
  VAPID_CLAIMS_EMAIL    — Contactadres voor Web Push (mailto:...)

Eenmalige instelling:
  intervals.icu → Settings → Connected Accounts → Garmin
  → "Sync planned workouts to Garmin" inschakelen
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import anthropic
import requests

import notify

log = logging.getLogger(__name__)
AMS = ZoneInfo("Europe/Amsterdam")

INTERVALS_BASE = "https://intervals.icu/api/v1/athlete"

# ── Atletenprofiel ─────────────────────────────────────────────────────────────

ATHLETE_PROFILE = {
    "name": "Ralph de Leeuw",
    "age": 47,
    "weight_kg": 77,
    "current_5k_min": 28,
    "current_5k_pace": "5:36",
    "target_5k_min": 26,
    "target_5k_pace": "5:12",
    "running_base": "enige basis — kan 5-10km lopen maar niet regelmatig geweest",
    "run_sessions": [
        {"day": "Tuesday",  "time": "20:00", "role": "speed"},
        {"day": "Saturday", "time": "09:00", "role": "long_run"},
    ],
    "schedule_note": "Hardloopdagen zijn standaard dinsdag en zaterdag, maar kunnen via health_input.json worden verplaatst.",
    "max_hr_estimate": 173,  # 220 - 47 jaar
    "hr_zones": {
        "Z1": "recovery (<104 bpm, <60% max)",
        "Z2": "aerobic base (104-121 bpm, 60-70% max)",
        "Z3": "tempo (121-138 bpm, 70-80% max)",
        "Z4": "threshold (138-155 bpm, 80-90% max)",
        "Z5": "VO2max (>155 bpm, >90% max)",
    },
}

# Pacezones op basis van huidig 5K (5:36/km) en doel (5:12/km)
PACE_ZONES = {
    "easy":       ("6:40", "7:10"),  # conversational, max 6:40/km
    "aerobic":    ("6:00", "6:30"),  # comfortabel uitdagend
    "threshold":  ("5:45", "5:55"),  # drempelintensiteit
    "5k_current": ("5:30", "5:42"),  # huidig 5K race tempo
    "5k_target":  ("5:08", "5:18"),  # doel 5K race tempo
    "fast_400":   ("5:10", "5:25"),  # intervaltempo 400m
    "fast_300":   ("5:20", "5:35"),  # intervaltempo 300m
    "fast_200":   ("5:00", "5:15"),  # intervaltempo 200m
}


# ── Gist helpers ───────────────────────────────────────────────────────────────

def _load_gist(gist_id: str, token: str) -> dict[str, str]:
    resp = requests.get(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}", "Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    return {
        name: meta.get("content", "")
        for name, meta in resp.json().get("files", {}).items()
    }


def _save_to_gist(gist_id: str, token: str, filename: str, content: str) -> None:
    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}", "Accept": "application/json"},
        json={"files": {filename: {"content": content}}},
        timeout=20,
    )
    resp.raise_for_status()


def _parse_json(raw: str, label: str) -> dict | list | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("%s is geen geldig JSON: %s", label, exc)
        return None


# ── Fitness context laden ──────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _cancelled_cf_dates(files: dict[str, str]) -> set[str]:
    """Return dates where the athlete cancelled CrossFit with no remaining active sign-up."""
    raw = files.get("sportbit_state.json", "")
    if not raw:
        return set()
    try:
        state = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    signed_up: dict = state.get("signed_up", {})
    cancelled: dict = state.get("cancelled", {})
    active_dates: set[str] = {
        info.get("date", "")
        for event_id, info in signed_up.items()
        if event_id not in cancelled and info.get("date")
    }
    return {
        info.get("date", "")
        for info in cancelled.values()
        if info.get("date") and info["date"] not in active_dates
    }


def _load_fitness_context(gist_id: str, token: str) -> dict:
    files = _load_gist(gist_id, token)

    wod_raw = files.get("sugarwod_wod.json", "")
    wod_data = _parse_json(wod_raw, "sugarwod_wod.json") or {}

    health_raw = files.get("health_input.json", "")
    health_input = _parse_json(health_raw, "health_input.json")

    plan_raw = files.get("running_plan.json", "")
    running_plan = _parse_json(plan_raw, "running_plan.json") or {}

    mfp_raw = files.get("myfitnesspal_nutrition.json", "")
    mfp_data = _parse_json(mfp_raw, "myfitnesspal_nutrition.json") or {}

    intervals_data = wod_data.get("intervals_data") or {}

    all_wods: list[dict] = wod_data.get("workouts") or []
    today_str = date.today().isoformat()
    cutoff_upcoming = (date.today() + timedelta(days=10)).isoformat()
    cutoff_recent = (date.today() - timedelta(days=14)).isoformat()

    cancelled = _cancelled_cf_dates(files)

    return {
        "wellness": intervals_data.get("wellness", {}).get("by_date", {}),
        "activities": intervals_data.get("activities", {}).get("by_date", {}),
        "health_input": health_input or {},
        "running_plan": running_plan,
        "upcoming_crossfit": [
            w for w in all_wods
            if today_str <= w.get("date", "") <= cutoff_upcoming
            and w.get("date", "") not in cancelled
        ],
        "recent_crossfit": [
            w for w in all_wods
            if cutoff_recent <= w.get("date", "") < today_str
            and w.get("date", "") not in cancelled
        ],
        "mfp_by_date": (mfp_data.get("diary") or {}).get("by_date") or {},
    }


# ── Context samenvatten voor Claude ───────────────────────────────────────────

def _next_weekday(weekday: int) -> date:
    """Geeft de eerstvolgende datum voor een gegeven weekdag (0=ma, 1=di, ..., 5=za)."""
    today = date.today()
    days_ahead = (weekday - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def _build_claude_context(ctx: dict) -> str:
    today = date.today()

    wellness_by_date: dict = ctx["wellness"]
    recent_dates = sorted(wellness_by_date.keys(), reverse=True)[:7]
    wellness_lines = []
    for d in recent_dates:
        w = wellness_by_date[d]
        parts = [f"  {d}:"]
        if w.get("hrv"):           parts.append(f"HRV={w['hrv']}ms")
        if w.get("hrv_sdnn"):      parts.append(f"SDNN={w['hrv_sdnn']}ms")
        if w.get("resting_hr"):    parts.append(f"resting_hr={w['resting_hr']}bpm")
        if w.get("avg_sleeping_hr"): parts.append(f"sleep_hr={w['avg_sleeping_hr']:.0f}bpm")
        if w.get("readiness") is not None: parts.append(f"readiness={w['readiness']}")
        if w.get("sleep_hrs"):     parts.append(f"sleep={w['sleep_hrs']}h")
        if w.get("sleep_score") is not None: parts.append(f"sleep_score={w['sleep_score']}")
        if w.get("respiration") is not None: parts.append(f"resp={w['respiration']:.1f}/min")
        if w.get("spo2") is not None:  parts.append(f"SpO2={w['spo2']}%")
        if w.get("ctl") is not None:   parts.append(f"CTL={w['ctl']}")
        if w.get("atl") is not None:   parts.append(f"ATL={w['atl']}")
        if w.get("tsb") is not None:   parts.append(f"TSB={w['tsb']}")
        wellness_lines.append(" ".join(parts))

    activities_by_date: dict = ctx["activities"]
    run_lines = []
    for d in sorted(activities_by_date.keys(), reverse=True)[:21]:
        for act in activities_by_date.get(d, []):
            act_type = (act.get("type") or "").lower()
            if not any(rt in act_type for rt in ["run", "running", "jog", "trailrun", "treadmill"]):
                continue
            parts = [f"  {d}: {act.get('name', 'Run')}"]
            if act.get("distance_m"):
                parts.append(f"{round(act['distance_m'] / 1000, 1)}km")
            if act.get("duration_min"):
                parts.append(f"{act['duration_min']}min")
            if act.get("avg_speed_ms") and act["avg_speed_ms"] > 0:
                spm = 1000 / act["avg_speed_ms"] / 60
                parts.append(f"pace {int(spm)}:{int((spm % 1) * 60):02d}/km")
            if act.get("avg_hr"):
                parts.append(f"avg.HR {act['avg_hr']}bpm")
            if act.get("max_hr"):
                parts.append(f"max.HR {act['max_hr']}bpm")
            if act.get("avg_cadence"):
                parts.append(f"cadence {round(act['avg_cadence'] * 2)}spm")
            if act.get("elevation_m"):
                parts.append(f"elev +{act['elevation_m']}m")
            if act.get("rpe"):
                parts.append(f"RPE {act['rpe']}")
            tl = act.get("training_load") or act.get("trimp")
            if tl is not None:
                parts.append(f"TL {round(tl)}")
            run_lines.append(" ".join(parts))
            # HR-zone verdeling tonen als aanwezig
            hz = act.get("hr_zone_times")
            if hz and isinstance(hz, list) and sum(hz) > 0:
                total = sum(hz)
                zone_labels = ["Z1", "Z2", "Z3", "Z4", "Z5"]
                zone_str = " ".join(
                    f"{zone_labels[i]}:{round(v/total*100)}%"
                    for i, v in enumerate(hz[:5]) if v > 0
                )
                run_lines.append(f"    HR zones: {zone_str}")
            # Laps (segmenten) tonen als aanwezig
            for i, lap in enumerate(act.get("laps", []), 1):
                lap_parts = [f"    lap {i}:"]
                if lap.get("distance_m"):
                    lap_parts.append(f"{lap['distance_m']}m")
                if lap.get("pace_per_km"):
                    lap_parts.append(f"{lap['pace_per_km']}/km")
                if lap.get("avg_hr"):
                    lap_parts.append(f"HR {lap['avg_hr']}bpm")
                if lap.get("avg_cadence"):
                    lap_parts.append(f"cadence {round(lap['avg_cadence'] * 2)}spm")
                run_lines.append(" ".join(lap_parts))

    running_plan = ctx["running_plan"]
    # Weeknummer op basis van startdatum plan; anders ophogen vanuit vorig plan
    week_number = 1
    plan_start_str = running_plan.get("plan_start_date")
    if plan_start_str:
        try:
            start_date = date.fromisoformat(plan_start_str)
            week_number = max(1, (today - start_date).days // 7 + 1)
        except ValueError:
            week_number = running_plan.get("week_number", 1)
    else:
        week_number = running_plan.get("week_number", 1)

    health_input = ctx.get("health_input") or {}

    # Optionele datumoverschrijvingen via health_input.json ("run_1", "run_2")
    # Formaat: "YYYY-MM-DDTHH:MM" of "YYYY-MM-DD" (tijd valt terug op default)
    def _parse_run_override(key: str, default_date: date, default_time: str) -> tuple[date, str]:
        raw = health_input.get(key, "")
        if not raw:
            return default_date, default_time
        try:
            if "T" in raw:
                dt = datetime.fromisoformat(raw)
                return dt.date(), dt.strftime("%H:%M")
            return date.fromisoformat(raw[:10]), default_time
        except ValueError:
            return default_date, default_time

    run1_date, run1_time = _parse_run_override("run_1", _next_weekday(1), "20:00")
    run2_date, run2_time = _parse_run_override("run_2", _next_weekday(5), "09:00")

    health_lines = [
        f"  - {k}: {v}"
        for k, v in health_input.items()
        if k not in ("date", "run_1", "run_2")
    ]

    sections = [
        f"Today's date: {today.isoformat()}",
        f"Week number in continuous 5K program: week {week_number}",
        f"Session 1 — speed work: {run1_date.isoformat()} at {run1_time} (use this date and time exactly)",
        f"Session 2 — long run: {run2_date.isoformat()} at {run2_time} (use this date and time exactly)",
        f"Current 5K pace: {ATHLETE_PROFILE['current_5k_pace']}/km ({ATHLETE_PROFILE['current_5k_min']} min)",
        f"Target 5K pace: {ATHLETE_PROFILE['target_5k_pace']}/km ({ATHLETE_PROFILE['target_5k_min']} min)",
    ]

    if wellness_lines:
        sections.append("Recovery data (last 7 days):\n" + "\n".join(wellness_lines))
    else:
        sections.append("Recovery data: not available")

    if run_lines:
        sections.append("Recent running activities:\n" + "\n".join(run_lines[:8]))
    else:
        sections.append("Recent running activities: none — this is the start of the program")

    # Upcoming CrossFit sessions
    upcoming_cf = ctx.get("upcoming_crossfit") or []
    if upcoming_cf:
        cf_lines = []
        dag_nl = ["ma", "di", "wo", "do", "vr", "za", "zo"]
        for w in sorted(upcoming_cf, key=lambda x: x.get("date", ""))[:10]:
            d = w.get("date", "")
            try:
                dag = dag_nl[date.fromisoformat(d).weekday()]
            except ValueError:
                dag = ""
            title = w.get("title") or w.get("name") or "WOD"
            desc = _strip_html(w.get("description") or "")[:120]
            line = f"  {d} ({dag}) — {title}"
            if desc:
                line += f"\n    {desc}"
            cf_lines.append(line)
        sections.append("Upcoming CrossFit sessions (actual schedule):\n" + "\n".join(cf_lines))
    else:
        sections.append("Upcoming CrossFit sessions: not available")

    # Recent CrossFit sessions (last 7 days for recovery context)
    recent_cf = ctx.get("recent_crossfit") or []
    recent_7 = [w for w in recent_cf if w.get("date", "") >= (today - timedelta(days=7)).isoformat()]
    if recent_7:
        rcf_lines = []
        for w in sorted(recent_7, key=lambda x: x.get("date", ""), reverse=True):
            d = w.get("date", "")
            title = w.get("title") or w.get("name") or "WOD"
            desc = _strip_html(w.get("description") or "")[:100]
            notes = w.get("athlete_notes") or ""
            line = f"  {d} — {title}"
            if desc:
                line += f" | {desc}"
            if notes:
                line += f"\n    Your notes: {notes[:100]}"
            rcf_lines.append(line)
        sections.append("Recent CrossFit sessions (last 7 days):\n" + "\n".join(rcf_lines))

    # MFP nutrition
    mfp_by_date = ctx.get("mfp_by_date") or {}
    mfp_dates = sorted(mfp_by_date.keys(), reverse=True)[:5]
    if mfp_dates:
        mfp_lines = []
        for d in mfp_dates:
            m = mfp_by_date[d]
            cal = m.get("calories", 0)
            if not cal:
                continue
            prot = round(m.get("protein_g") or 0)
            carbs = round(m.get("carbs_g") or 0)
            fat = round(m.get("fat_g") or 0)
            mfp_lines.append(f"  {d}: {cal} kcal, {prot}g protein, {carbs}g carbs, {fat}g fat")
        if mfp_lines:
            sections.append("Nutrition last 5 days (MyFitnessPal):\n" + "\n".join(mfp_lines))

    if health_lines:
        sections.append("Subjective health scores:\n" + "\n".join(health_lines))

    return "\n\n".join(sections)


# ── Claude prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a professional running coach. You create training schedules for Ralph de Leeuw:
- 47 years old, 77kg, CrossFit 5x/week (actual schedule provided in context), runs 2x/week
- Current 5K: ~28 min (5:36/km) | Goal: 26 min (5:12/km)
- Default: Tuesday 20:00 = speed work | Saturday 09:00 = long run
- The exact dates and times are provided in the context — always use them exactly
- Use the upcoming CrossFit schedule in the context to avoid scheduling hard speed sessions on days with heavy CrossFit (same day or day after)

Pace zones (always calibrate to recovery status via HRV/TSB):
- Conversational (max):  6:40/km — "no faster than 6:40/km"
- Aerobic:               6:00-6:20/km
- Threshold:             5:45-5:55/km
- 5K race pace (now):    5:30-5:42/km
- Interval pace 800m:    5:20-5:30/km
- Interval pace 400m:    5:10-5:25/km
- Interval pace 300m:    5:20-5:35/km
- Interval pace 200m:    5:00-5:15/km

HR zones (max HR ~173 bpm, age 47):
- Z1 recovery:   <104 bpm  — warmup, cooldown, recovery walk
- Z2 aerobic:    104-121   — easy runs, long runs, base building
- Z3 tempo:      121-138   — aerobic threshold, fartlek surges
- Z4 threshold:  138-155   — tempo runs, threshold intervals
- Z5 VO2max:     >155      — hard intervals (400m, 300m, 200m)

Periodization (continuous, no end date):
- Weeks 1-4:   base building — easy long runs + light fartlek, max 6km Saturday
- Weeks 5-8:   first structured work — rolling repeats (300m/400m), progressive long runs
- Weeks 9-12:  intensity — Fast 8-4-2s style, threshold intervals, longer long runs
- Week 13+:    consolidation + race prep — every 4th week recovery week (30% less volume)
- Low HRV (<35ms) or negative TSB (<-15): always choose the lighter variant

Output: return ONLY valid JSON (no markdown, no explanation):
[
  {
    "date": "YYYY-MM-DD",
    "session": "speed|long_run",
    "type": "easy_run|fartlek|interval_run|progressive_run|tempo_run",
    "name": "Short English session name (like Runna: 'Rolling 300s', 'Progressive long run')",
    "description": "1-2 sentences about the goal of this session",
    "total_distance_km": <float>,
    "steps": [
      <steps — see format below>
    ]
  }
]

Step formats:
  Warm-up:      {"type":"warmup",   "distance_m":<int>, "pace_min":"M:SS", "pace_max":"M:SS", "hr_zone":"Z1"}
  Easy/long run:{"type":"run",      "distance_m":<int>, "pace_min":"M:SS", "pace_max":"M:SS", "hr_zone":"Z2"}
  Interval:     {"type":"run",      "distance_m":<int>, "pace_min":"M:SS", "pace_max":"M:SS", "hr_zone":"Z4"}
  Repeat:       {"type":"repeat",   "count":<int>, "children":[<steps>]}
  Walking rest: {"type":"rest",     "duration_s":<int>}
  Cool-down:    {"type":"cooldown", "distance_m":<int>, "pace_min":"M:SS", "pace_max":"M:SS", "hr_zone":"Z1"}

pace_min = fastest allowed pace (lower M:SS value, e.g. "6:20"), pace_max = slowest allowed pace (higher M:SS value, e.g. "6:40").
Always provide both pace_min and pace_max as a range — this shows a needle gauge on Garmin instead of a fixed marker.
Use the pace zone ranges from the table above directly as pace_min/pace_max:
  warmup/cooldown:  pace_min="6:20", pace_max="6:40"  (~20s spread, conversational)
  easy/long run:    use the aerobic zone range, e.g. pace_min="6:00", pace_max="6:20"
  interval 400m:    pace_min="5:10", pace_max="5:25"
  interval 300m:    pace_min="5:20", pace_max="5:35"
  interval 800m:    pace_min="5:20", pace_max="5:30"

HR zone guidance per step:
  warmup/cooldown → always "Z1"
  easy/long run   → "Z2" (base), "Z2-Z3" (aerobic push)
  fartlek surge   → "Z3" or "Z3-Z4"
  tempo/threshold → "Z4"
  hard interval   → "Z4-Z5"

IMPORTANT: Always use distance_m for every run step — warmup, cooldown, easy runs, and long runs alike.
Never use duration_min. The athlete sees distance remaining on their Garmin, not a countdown timer.
Pace: write as "M:SS" (e.g. "6:40", "5:35").
Walking rest after the entire repeat block (not per repeat) if it is a long break.
Saturday session: always progressive_run or easy_run. Structure as warmup (1km) + main run + cooldown (1km).
Total distance 5-9km depending on week number."""


def _generate_plan_claude(context_text: str) -> list[dict]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": "Generate the running schedule for the upcoming week:\n\n" + context_text,
        }],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:].lstrip()

    return json.loads(raw)


# ── Pace helpers ───────────────────────────────────────────────────────────────

def _pace_to_sec_per_km(pace: str) -> int:
    """Converteer "5:35" naar seconden per km (335)."""
    parts = pace.split(":")
    return int(parts[0]) * 60 + int(parts[1])


# ── workout_doc bouwen ─────────────────────────────────────────────────────────

def _step_to_doc(step: dict) -> dict | None:
    """Converteer een Claude-stap naar het exacte intervals.icu workout_doc formaat.

    Gebaseerd op de GET /events response van een handmatig aangemaakte workout.
    Pace zit als {"units": "secs/km", "value": <int>} op het step-niveau.
    Warmup/cooldown zijn boolean flags + intensity string, geen type-veld.
    """
    stype = step.get("type")

    def pace_secs(s: dict) -> int | None:
        """Midpoint of pace range, or single value for legacy steps."""
        pace_min = s.get("pace_min")
        pace_max = s.get("pace_max")
        if pace_min and pace_max:
            return (_pace_to_sec_per_km(pace_min) + _pace_to_sec_per_km(pace_max)) // 2
        pace_str = s.get("pace_target") or pace_max or pace_min
        return _pace_to_sec_per_km(pace_str) if pace_str else None

    def pace_range_str(s: dict) -> str:
        """Return 'M:SS-M:SS' range string for ICU text / labels."""
        pace_min = s.get("pace_min")
        pace_max = s.get("pace_max")
        if pace_min and pace_max:
            return f"{pace_min}-{pace_max}"
        pace = s.get("pace_target") or pace_max or pace_min
        return pace or ""

    def calc_duration(s: dict) -> int | None:
        if s.get("duration_s"):
            return int(s["duration_s"])
        if s.get("duration_min"):
            return int(s["duration_min"] * 60)
        dist_m = s.get("distance_m")
        pace_str = s.get("pace_max") or s.get("pace_min") or s.get("pace_target")
        if dist_m and pace_str:
            return int(dist_m / 1000 * _pace_to_sec_per_km(pace_str))
        return None

    if stype == "warmup":
        dist_m = step.get("distance_m")
        dur = calc_duration(step)
        if not dist_m and not dur:
            return None
        hr_zone = step.get("hr_zone", "Z1")
        pr = pace_range_str(step)
        pace_label = f" {pr}" if pr else ""
        text = f"Warmup {dist_m/1000:.1f}km{pace_label} {hr_zone}" if dist_m else f"Warmup{pace_label} {hr_zone}"
        doc: dict = {"warmup": True, "intensity": "warmup", "text": text}
        if dist_m:
            doc["distance"] = dist_m
        if dur:
            doc["duration"] = dur
        ps = pace_secs(step)
        if ps:
            doc["pace"] = {"units": "secs/km", "value": ps}
        doc["hr"] = hr_zone
        return doc

    if stype == "cooldown":
        dist_m = step.get("distance_m")
        dur = calc_duration(step)
        if not dist_m and not dur:
            return None
        hr_zone = step.get("hr_zone", "Z1")
        pr = pace_range_str(step)
        pace_label = f" {pr}" if pr else ""
        text = f"Cooldown {dist_m/1000:.1f}km{pace_label} {hr_zone}" if dist_m else f"Cooldown{pace_label} {hr_zone}"
        doc = {"cooldown": True, "intensity": "cooldown", "text": text}
        if dist_m:
            doc["distance"] = dist_m
        if dur:
            doc["duration"] = dur
        ps = pace_secs(step)
        if ps:
            doc["pace"] = {"units": "secs/km", "value": ps}
        doc["hr"] = hr_zone
        return doc

    if stype == "run":
        dist_m = step.get("distance_m")
        hr_zone = step.get("hr_zone")
        dur = calc_duration(step)
        if not dur:
            return None
        hr_str = f" {hr_zone}" if hr_zone else ""
        pr = pace_range_str(step)
        if dist_m:
            if pr:
                text = f"{dist_m}m @ {pr}/km{hr_str}"
            else:
                text = f"Easy {dist_m/1000:.1f}km{hr_str}"
            doc = {"distance": dist_m, "duration": dur}
        else:
            text = f"Easy run{(' @ ' + pr + '/km') if pr else ''}{hr_str}"
            doc = {"duration": dur}
        doc["text"] = text
        ps = pace_secs(step)
        if ps:
            doc["pace"] = {"units": "secs/km", "value": ps}
        if hr_zone:
            doc["hr"] = hr_zone
        return doc

    if stype == "rest":
        dur = step.get("duration_s") or (int(step["duration_min"] * 60) if step.get("duration_min") else None)
        if not dur:
            return None
        return {"rest": True, "intensity": "rest", "duration": dur, "text": "Recovery walk"}

    if stype == "repeat":
        children = [_step_to_doc(c) for c in step.get("children", [])]
        children = [c for c in children if c]
        if not children:
            return None
        count = step.get("count", 1)
        total_dist = sum(c.get("distance", 0) for c in children) * count
        total_dur = sum(c.get("duration", 0) for c in children) * count
        doc = {"reps": count, "text": f"Main set {count}x", "steps": children}
        if total_dist:
            doc["distance"] = total_dist
        if total_dur:
            doc["duration"] = total_dur
        return doc

    return None


def _build_workout_doc(spec: dict) -> dict | None:
    steps = [_step_to_doc(s) for s in spec.get("steps", [])]
    steps = [s for s in steps if s]
    if not steps:
        return None
    total_dist = sum(s.get("distance", 0) for s in steps)
    total_dur = sum(s.get("duration", 0) for s in steps)
    return {
        "steps": steps,
        "locales": [],
        "options": {},
        "distance": total_dist,
        "duration": total_dur,
        "description": _build_icu_workout_text(spec),
    }


# ── Beschrijvingstekst (Runna-stijl) ──────────────────────────────────────────

def _build_description(spec: dict) -> str:
    lines = []
    if spec.get("description"):
        lines.append(spec["description"])
        lines.append("")

    for step in spec.get("steps", []):
        stype = step.get("type")

        if stype == "warmup":
            dist = step.get("distance_m", "")
            pace = step.get("pace_max", "")
            dist_str = f"{dist/1000:.1f}km " if dist else ""
            pace_str = f" (no faster than {pace}/km)" if pace else ""
            lines.append(f"{dist_str}warm-up in conversational pace{pace_str}")

        elif stype == "cooldown":
            dist = step.get("distance_m", "")
            dist_str = f"{dist/1000:.1f}km " if dist else ""
            lines.append(f"\n{dist_str}cool-down in conversational pace (or slower!)")

        elif stype == "run":
            dist = step.get("distance_m")
            dur = step.get("duration_min")
            pace = step.get("pace_target") or step.get("pace_max")
            if dist:
                pace_str = f" at {pace}/km" if pace else ""
                lines.append(f"{dist}m{pace_str}")
            elif dur:
                pace_str = f" (max {pace}/km)" if pace else ""
                lines.append(f"{dur} min{pace_str}")

        elif stype == "repeat":
            count = step.get("count", "?")
            lines.append(f"\nRepeat the following {count}x:")
            lines.append("----------")
            for child in step.get("children", []):
                ct = child.get("type")
                if ct == "run":
                    dist = child.get("distance_m")
                    pace = child.get("pace_target") or child.get("pace_max")
                    pace_str = f" at {pace}/km" if pace else ""
                    lines.append(f"{dist}m{pace_str}" if dist else "run")
                elif ct == "rest":
                    dur_s = child.get("duration_s", 0)
                    lines.append(f"{dur_s}s walking recovery")
            lines.append("----------")

        elif stype == "rest":
            dur_s = step.get("duration_s", 0)
            lines.append(f"\n{dur_s}s walking recovery")

    week = spec.get("week_number", "")
    if week:
        lines.append(f"\n5K Improvement Program (Week {week})")

    return "\n".join(lines)


# ── Intervals.icu tekst-format (parsed door server naar stappen + grafiek) ────

def _build_icu_workout_text(spec: dict) -> str:
    """Bouw intervals.icu tekst-syntax op basis van Claude-stappen.

    Dit formaat wordt door intervals.icu server-side geparsed naar
    gestructureerde workout-stappen (grafiek + Garmin-sync).
    Indeling: "<afstand>m <tempo>/km [Warmup|Cooldown]" per stap,
    herhalingen als "Nx" gevolgd door de deelstappen.
    """
    lines = []

    def _pace_range(step: dict) -> str:
        pace_min = step.get("pace_min")
        pace_max = step.get("pace_max")
        if pace_min and pace_max:
            return f"{pace_min}-{pace_max}"
        pace = step.get("pace_target") or pace_max or pace_min
        return pace or ""

    def _step_lines(step: dict) -> list[str]:
        stype = step.get("type")
        hr = step.get("hr_zone", "")
        hr_str = f" {hr}" if hr else ""
        result = []
        if stype == "warmup":
            dist = step.get("distance_m")
            pr = _pace_range(step)
            pace_part = f" {pr}" if pr else ""
            if dist:
                result.append(f"{dist}m{pace_part}{hr_str} Warmup")
        elif stype == "cooldown":
            dist = step.get("distance_m")
            pr = _pace_range(step)
            pace_part = f" {pr}" if pr else ""
            if dist:
                result.append(f"{dist}m{pace_part}{hr_str} Cooldown")
        elif stype == "run":
            dist = step.get("distance_m")
            pr = _pace_range(step)
            pace_part = f" {pr}" if pr else ""
            if dist:
                result.append(f"{dist}m{pace_part}{hr_str}")
        elif stype == "rest":
            dur = step.get("duration_s")
            if dur:
                result.append(f"{dur}s Rest")
        elif stype == "repeat":
            count = step.get("count", 1)
            result.append(f"{count}x")
            for child in step.get("children", []):
                result.extend(_step_lines(child))
        return result

    for step in spec.get("steps", []):
        lines.extend(_step_lines(step))

    return " ".join(lines)


def _build_expanded_description(spec: dict) -> str:
    """Bouw de volledige description op zoals de intervals.icu UI dat doet.

    Format (exact zoals handmatig aangemaakte workout):
      {icu_one_liner}

      Warmup
      - Warmup 1km 6:40/km Pace intensity=warmup

      Main set 6x
      - 0.2km 5:35/km Pace
      - 0.2km 6:40/km Pace

      Cooldown
      - Cooldown 1.4km 6:40/km Pace intensity=cooldown
    """
    def dist_str(m: int) -> str:
        km = m / 1000
        return f"{km:g}km"

    def _pr(s: dict) -> str:
        pace_min = s.get("pace_min")
        pace_max = s.get("pace_max")
        if pace_min and pace_max:
            return f"{pace_min}-{pace_max}"
        pace = s.get("pace_target") or pace_max or pace_min
        return pace or ""

    sections: list[str] = []
    for step in spec.get("steps", []):
        stype = step.get("type")
        dist = step.get("distance_m", 0)
        pr = _pr(step)
        pace_label = f" {pr}" if pr else ""
        hr = step.get("hr_zone", "")
        hr_str = f" {hr}" if hr else ""

        if stype == "warmup":
            sections.append(f"Warmup\n- Warmup {dist_str(dist)}{pace_label} Pace{hr_str} intensity=warmup")

        elif stype == "cooldown":
            sections.append(f"Cooldown\n- Cooldown {dist_str(dist)}{pace_label} Pace{hr_str} intensity=cooldown")

        elif stype == "run":
            sections.append(f"- {dist_str(dist)}{pace_label} Pace{hr_str}")

        elif stype == "repeat":
            count = step.get("count", 1)
            lines = [f"Main set {count}x"]
            for child in step.get("children", []):
                cdist = child.get("distance_m", 0)
                cpr = _pr(child)
                cpace_label = f" {cpr}" if cpr else ""
                chr_zone = child.get("hr_zone", "")
                chr_str = f" {chr_zone}" if chr_zone else ""
                lines.append(f"- {dist_str(cdist)}{cpace_label} Pace{chr_str}")
            sections.append("\n".join(lines))

    icu_text = _build_icu_workout_text(spec)
    return icu_text + "\n\n" + "\n\n".join(sections)


# ── Intervals.icu event bouwen ─────────────────────────────────────────────────

def _build_intervals_event(spec: dict) -> dict:
    # Gebruik de tijd uit spec als die er is, anders val terug op sessie-rol
    if spec.get("time"):
        time_str = spec["time"] if ":" in spec["time"] and len(spec["time"]) >= 5 else "20:00:00"
        if len(time_str) == 5:
            time_str += ":00"
    else:
        session_role = spec.get("session", "speed")
        time_str = "20:00:00" if session_role == "speed" else "09:00:00"

    # De intervals.icu UI parsed ICU-tekst client-side, genereeert de expanded description
    # (met Warmup / Main set Nx / Cooldown secties) en stuurt dit als description mee.
    # De server parseert deze expanded description naar workout_doc.steps.
    sent_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    expanded = _build_expanded_description(spec)
    description = f"{expanded}\n\nSent: {sent_at}" if expanded else f"Sent: {sent_at}"

    event: dict = {
        "start_date_local": f"{spec['date']}T{time_str}",
        "category": "WORKOUT",
        "type": "Run",
        "name": spec["name"],
        "description": description,
    }

    workout_doc = _build_workout_doc(spec)
    if workout_doc:
        event["workout_doc"] = workout_doc

    return event


# ── Push naar intervals.icu ────────────────────────────────────────────────────

def cleanup_completed_events(athlete_id: str, api_key: str, gist_id: str, github_token: str) -> None:
    """Verwijder geplande events waarvan de activiteit al geregistreerd is in intervals.icu.

    Draait dagelijks (via fetch_sugarwod.py). Zodra Garmin een hardloopactiviteit
    synchroniseert naar intervals.icu op de datum van een gepland event, wordt het
    geplande event verwijderd zodat er nog maar 1 entry zichtbaar is.
    """
    files = _load_gist(gist_id, github_token)
    plan: dict = _parse_json(files.get("running_plan.json", ""), "running_plan.json") or {}
    workouts = plan.get("workouts", [])

    today = date.today().isoformat()
    past = [w for w in workouts if w.get("event_id") and w.get("date", "9999") < today]
    if not past:
        return

    session = requests.Session()
    session.auth = ("API_KEY", api_key)
    run_types = {"run", "running", "trailrun", "treadmill"}
    changed = False

    for workout in past:
        workout_date = workout["date"]
        event_id = workout["event_id"]
        try:
            resp = session.get(
                f"{INTERVALS_BASE}/{athlete_id}/activities",
                params={"oldest": workout_date, "newest": workout_date},
                timeout=20,
            )
            if not resp.ok:
                log.warning("Activiteiten-check mislukt voor %s: %s", workout_date, resp.status_code)
                continue
            activities = resp.json() if isinstance(resp.json(), list) else []
            has_run = any(
                run_types & {(a.get("type") or "").lower().replace(" ", "")}
                for a in activities
            )
            if has_run:
                del_resp = session.delete(f"{INTERVALS_BASE}/{athlete_id}/events/{event_id}", timeout=20)
                if del_resp.ok:
                    log.info("Event %s verwijderd — activiteit op %s gevonden", event_id, workout_date)
                    workout["event_id"] = None
                    changed = True
                else:
                    log.warning("Kon event %s niet verwijderen: %s", event_id, del_resp.status_code)
        except Exception as exc:
            log.warning("Fout bij cleanup event %s (%s): %s", event_id, workout_date, exc)

    if changed:
        _save_to_gist(gist_id, github_token, "running_plan.json",
                      json.dumps(plan, indent=2, ensure_ascii=False))


def _delete_old_intervals_events(athlete_id: str, api_key: str, existing_plan: dict) -> None:
    """Verwijder bestaande intervals.icu events zodat er geen duplicaten ontstaan bij herhaalde runs."""
    old_ids = [w["event_id"] for w in existing_plan.get("workouts", []) if w.get("event_id")]
    if not old_ids:
        return
    session = requests.Session()
    session.auth = ("API_KEY", api_key)
    for eid in old_ids:
        try:
            resp = session.delete(f"{INTERVALS_BASE}/{athlete_id}/events/{eid}", timeout=20)
            if resp.ok:
                log.info("Oud intervals.icu event %s verwijderd", eid)
            else:
                log.warning("Kon oud event %s niet verwijderen: %s", eid, resp.status_code)
        except Exception as exc:
            log.warning("Fout bij verwijderen oud event %s: %s", eid, exc)


def _push_to_intervals(athlete_id: str, api_key: str, events: list[dict]) -> list[dict | None]:
    session = requests.Session()
    session.auth = ("API_KEY", api_key)
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    results: list[dict | None] = []
    for event in events:
        url = f"{INTERVALS_BASE}/{athlete_id}/events"
        try:
            resp = session.post(url, json=event, timeout=20)
            if not resp.ok:
                log.error(
                    "Fout bij aanmaken event '%s': %s — %s",
                    event.get("name"), resp.status_code, resp.text[:300],
                )
                results.append(None)
                continue
            result = resp.json()
            stored_doc = result.get("workout_doc")
            log.info(
                "Event aangemaakt: '%s' op %s om %s (id: %s, stappen: %d)",
                event["name"],
                event["start_date_local"][:10],
                event["start_date_local"][11:16],
                result.get("id"),
                len((stored_doc or {}).get("steps") or []),
            )

            # PUT-fallback als POST geen stappen opleverde
            event_id = result.get("id")
            if event_id and event.get("workout_doc") and not (stored_doc or {}).get("steps"):
                log.warning("POST leverde geen stappen op — retry via PUT voor event %s", event_id)
                put_url = f"{INTERVALS_BASE}/{athlete_id}/events/{event_id}"
                put_payload: dict = {"workout_doc": event["workout_doc"]}
                if event.get("description"):
                    put_payload["description"] = event["description"]
                put_resp = session.put(put_url, json=put_payload, timeout=20)
                if put_resp.ok:
                    put_steps = len(((put_resp.json().get("workout_doc") or {}).get("steps")) or [])
                    log.info("PUT geslaagd: %d stappen opgeslagen", put_steps)
                else:
                    log.warning("PUT ook mislukt: %s — %s", put_resp.status_code, put_resp.text[:200])

            results.append(result)
        except Exception as exc:
            log.error("Fout bij aanmaken event '%s': %s", event.get("name"), exc)
            results.append(None)

    return results


# ── Google Agenda helpers ──────────────────────────────────────────────────────

def _gcal_event_body(spec: dict) -> dict | None:
    time_str = spec.get("time", "20:00" if spec.get("session") == "speed" else "09:00")
    if len(time_str) == 5:
        time_str += ":00"
    try:
        dt_start = datetime.fromisoformat(f"{spec['date']}T{time_str}")
    except (ValueError, KeyError):
        return None

    dist_km = spec.get("total_distance_km")
    dur_min  = spec.get("total_duration_min")
    if dur_min:
        dt_end = dt_start + timedelta(minutes=dur_min)
    elif dist_km:
        dt_end = dt_start + timedelta(minutes=round(float(dist_km) * 6.5))
    else:
        dt_end = dt_start + timedelta(hours=1)

    name      = spec.get("name") or spec.get("type") or "Hardloopworkout"
    dist_str  = f" ({dist_km}km)" if dist_km else ""
    desc      = spec.get("description") or ""
    week_nr   = spec.get("week_number")
    if week_nr:
        desc = f"5K-programma week {week_nr}\n\n" + desc

    return {
        "summary":     f"🏃 {name}{dist_str}",
        "description": desc,
        "start": {"dateTime": dt_start.isoformat(), "timeZone": "Europe/Amsterdam"},
        "end":   {"dateTime": dt_end.isoformat(),   "timeZone": "Europe/Amsterdam"},
    }


def _gcal_push(specs: list[dict], calendar_id: str, creds_json: str,
               existing_plan: dict) -> None:
    """Maak Google Agenda events aan; verwijder eerst oud event als dat bestaat."""
    try:
        from google_calendar_sync import GoogleCalendarSync
        cal = GoogleCalendarSync(creds_json=creds_json)
    except Exception as exc:
        log.error("Fout bij opzetten Google Agenda service: %s", exc)
        return

    # Bestaande gcal_event_ids per sessie om duplicaten te voorkomen
    old_ids: dict[str, str] = {
        w.get("session", ""): w["gcal_event_id"]
        for w in existing_plan.get("workouts", [])
        if w.get("gcal_event_id")
    }

    for spec in specs:
        old_id = old_ids.get(spec.get("session", ""))
        if old_id:
            try:
                cal.service.events().delete(calendarId=calendar_id, eventId=old_id).execute()
                log.info("Oud Google Agenda event %s verwijderd", old_id)
            except Exception as exc:
                log.warning("Kon oud event %s niet verwijderen: %s", old_id, exc)

        body = _gcal_event_body(spec)
        if not body:
            continue
        try:
            result = cal.create_event(calendar_id=calendar_id, event_details=body)
            spec["gcal_event_id"] = result.get("id")
            log.info("Google Agenda event aangemaakt: '%s' op %s (%s)",
                     spec.get("name"), spec.get("date"), spec["gcal_event_id"])
        except Exception as exc:
            log.error("Fout bij aanmaken Google Agenda event voor %s: %s",
                      spec.get("date"), exc)


# ── iCal genereren ────────────────────────────────────────────────────────────

def _generate_ical(specs: list[dict]) -> str:
    """Genereer iCal content voor alle hardloopworkouts."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Sportbit//Running Workouts//NL",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Hardloopplan",
        "X-WR-TIMEZONE:Europe/Amsterdam",
    ]

    for spec in specs:
        date_str = spec.get("date", "")
        time_str = spec.get("time", "20:00" if spec.get("session") == "speed" else "09:00")
        if len(time_str) == 5:
            time_str += ":00"
        try:
            dt_start = datetime.fromisoformat(f"{date_str}T{time_str}")
        except ValueError:
            continue

        dist_km = spec.get("total_distance_km")
        dur_min = spec.get("total_duration_min")
        if dur_min:
            dt_end = dt_start + timedelta(minutes=dur_min)
        elif dist_km:
            dt_end = dt_start + timedelta(minutes=round(float(dist_km) * 6.5))
        else:
            dt_end = dt_start + timedelta(hours=1)

        dtstart = dt_start.strftime("%Y%m%dT%H%M%S")
        dtend   = dt_end.strftime("%Y%m%dT%H%M%S")

        name = spec.get("name") or spec.get("type") or "Hardloopworkout"
        dist_str = f" ({dist_km}km)" if dist_km else ""
        summary  = f"🏃 {name}{dist_str}"

        raw_desc = spec.get("description") or ""
        description = raw_desc.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,")

        week_nr = spec.get("week_number")
        if week_nr:
            description = f"5K-programma week {week_nr}\\n\\n" + description

        uid = f"sportbit-run-{date_str}@sportbit"
        now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART;TZID=Europe/Amsterdam:{dtstart}",
            f"DTEND;TZID=Europe/Amsterdam:{dtend}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
            "CATEGORIES:Hardlopen",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _save_ical_to_gist(gist_id: str, token: str, ical_content: str) -> None:
    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}", "Accept": "application/json"},
        json={"files": {"running_workouts.ics": {"content": ical_content}}},
        timeout=20,
    )
    resp.raise_for_status()
    html_url = resp.json().get("html_url", "")
    if html_url:
        parts = html_url.rstrip("/").split("/")
        if len(parts) >= 2:
            username = parts[-2]
            raw_url = (
                f"https://gist.githubusercontent.com/{username}/{gist_id}"
                "/raw/running_workouts.ics"
            )
            log.info("iCal opgeslagen → Google Agenda-abonnement URL: %s", raw_url)


def _estimate_5k_seconds(specs: list[dict]) -> int | None:
    """
    Schat de huidige 5K-tijd op basis van de intervaltempo's in de speed-sessie.

    Gebruikt alleen de speed-sessie (niet de lange duurloop) en alleen
    pace_target velden (niet pace_max, die gelden voor easy runs).
    Intervaltempos voor 300-400m zijn ~6% sneller dan 5K race pace.
    """
    interval_paces_spm: list[float] = []
    for spec in specs:
        if spec.get("session") != "speed":
            continue
        for step in spec.get("steps", []):
            if step.get("type") == "repeat":
                for child in step.get("children", []):
                    if child.get("type") == "run":
                        pace_str = child.get("pace_target")  # alleen expliciete intervaltargets
                        if pace_str:
                            try:
                                mins, secs = pace_str.split(":")
                                spm = int(mins) * 60 + int(secs)
                                # Filter out easy paces (> 6:10/km) — die horen niet in een interval
                                if spm <= 370:
                                    interval_paces_spm.append(spm)
                            except (ValueError, AttributeError):
                                pass

    if not interval_paces_spm:
        return None

    interval_paces_spm.sort()
    median_pace = interval_paces_spm[len(interval_paces_spm) // 2]
    # 300-400m intervaltempo is ~6% sneller dan 5K race pace
    race_pace_spm = median_pace * 1.06
    return round(race_pace_spm * 5)  # 5 km


def _save_plan_to_gist(gist_id: str, token: str, specs: list[dict], week_number: int) -> None:
    plan_start = specs[0]["date"] if specs else date.today().isoformat()
    estimated_5k = _estimate_5k_seconds(specs)
    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week_number": week_number,
        "plan_start_date": plan_start,
        "workouts": specs,
    }
    if estimated_5k is not None:
        plan["estimated_5k_seconds"] = estimated_5k
        mins, secs = divmod(estimated_5k, 60)
        log.info("Geschatte 5K tijd: %d:%02d", mins, secs)
    _save_to_gist(gist_id, token, "running_plan.json", json.dumps(plan, indent=2, ensure_ascii=False))
    log.info("running_plan.json opgeslagen in Gist (week %d)", week_number)


def _notify(specs: list[dict]) -> None:
    lines = ["Hardloopschema deze week:"]
    for s in specs:
        d = datetime.strptime(s["date"], "%Y-%m-%d")
        dag = ["ma", "di", "wo", "do", "vr", "za", "zo"][d.weekday()]
        time_str = s.get("time", "20:00" if s.get("session") == "speed" else "09:00")
        dist = s.get("total_distance_km", "?")
        lines.append(f"\n{dag} {d.day}/{d.month} {time_str} — {s['name']} ({dist}km)")
    notify.send_notification("Hardloopplan klaar 🏃", "\n".join(lines))


# ── Main ───────────────────────────────────────────────────────────────────────

def _repush_existing(athlete_id: str, api_key: str, gist_id: str, github_token: str) -> None:
    """Laad bestaande workouts uit de Gist, herbouw workout_doc en push opnieuw naar intervals.icu."""
    log.info("Laden bestaand hardloopplan uit Gist...")
    gist_files = _load_gist(gist_id, github_token)
    plan_raw = gist_files.get("running_plan.json", "")
    plan: dict = _parse_json(plan_raw, "running_plan.json") or {}
    specs: list[dict] = plan.get("workouts", [])
    if not specs:
        log.error("Geen workouts gevonden in running_plan.json — niets te doen")
        sys.exit(1)
    log.info("%d workout(s) gevonden in plan", len(specs))

    log.info("Oude intervals.icu events verwijderen...")
    _delete_old_intervals_events(athlete_id, api_key, plan)

    log.info("Workout_docs herbouwen en opnieuw pushen...")
    events = [_build_intervals_event(s) for s in specs]
    results = _push_to_intervals(athlete_id, api_key, events)

    for spec, event, result in zip(specs, events, results):
        if result:
            spec["event_id"] = result.get("id")
        if "workout_doc" in event:
            spec["workout_doc"] = event["workout_doc"]

    _save_to_gist(gist_id, github_token, "running_plan.json",
                  json.dumps(plan, indent=2, ensure_ascii=False))
    log.info("running_plan.json bijgewerkt met nieuwe event IDs")
    log.info("Klaar! %d workout(s) opnieuw gepusht naar intervals.icu.", len(specs))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    repush = "--repush" in sys.argv

    athlete_id   = os.environ.get("INTERVALS_ATHLETE_ID", "").strip()
    api_key      = os.environ.get("INTERVALS_API_KEY", "").strip()
    gist_id      = os.environ.get("GIST_ID", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()

    required = [
        ("INTERVALS_ATHLETE_ID", athlete_id),
        ("INTERVALS_API_KEY", api_key),
        ("GIST_ID", gist_id),
        ("GITHUB_TOKEN", github_token),
    ]
    if not repush:
        required.append(("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")))

    missing = [name for name, val in required if not val]
    if missing:
        log.error("Vereiste environment variables ontbreken: %s", ", ".join(missing))
        sys.exit(1)

    if repush:
        _repush_existing(athlete_id, api_key, gist_id, github_token)
        return

    log.info("Laden fitnessdata uit Gist...")
    ctx = _load_fitness_context(gist_id, github_token)

    context_text = _build_claude_context(ctx)
    log.info("Context klaar:\n%s", context_text)

    log.info("Hardloopplan genereren via Claude...")
    specs = _generate_plan_claude(context_text)
    log.info("Claude genereerde %d workout(s)", len(specs))
    for s in specs:
        log.info("  - %s [%s]: %s (%s km, %s)", s["date"], s.get("session"), s["name"],
                 s.get("total_distance_km", "?"), s.get("type"))

    # Annoteer week_number in specs voor beschrijvingstekst
    running_plan = ctx.get("running_plan", {})
    today = date.today()
    plan_start_str = running_plan.get("plan_start_date")
    if plan_start_str:
        try:
            start = date.fromisoformat(plan_start_str)
            week_number = max(1, (today - start).days // 7 + 1)
        except ValueError:
            week_number = running_plan.get("week_number", 1)
    else:
        week_number = 1
    for s in specs:
        s.setdefault("week_number", week_number)

    # Annoteer de werkelijke starttijden vanuit de context (zodat _build_intervals_event ze kan gebruiken)
    health_input = ctx.get("health_input") or {}
    _run1_raw = health_input.get("run_1", "")
    _run2_raw = health_input.get("run_2", "")
    _run1_time = (datetime.fromisoformat(_run1_raw).strftime("%H:%M") if "T" in _run1_raw else "20:00") if _run1_raw else "20:00"
    _run2_time = (datetime.fromisoformat(_run2_raw).strftime("%H:%M") if "T" in _run2_raw else "09:00") if _run2_raw else "09:00"
    for s in specs:
        if s.get("session") == "speed":
            s.setdefault("time", _run1_time)
        else:
            s.setdefault("time", _run2_time)

    # Sla de volledige beschrijvingstekst (inclusief stap-voor-stap) op in elk spec
    for s in specs:
        s["full_description"] = _build_description(s)

    events = [_build_intervals_event(s) for s in specs]

    log.info("Oude intervals.icu events opruimen...")
    _delete_old_intervals_events(athlete_id, api_key, ctx.get("running_plan", {}))

    log.info("Workouts pushen naar intervals.icu...")
    results = _push_to_intervals(athlete_id, api_key, events)

    # Sla event_id en workout_doc op in specs zodat reschedule ze kan gebruiken
    for spec, event, result in zip(specs, events, results):
        if result:
            spec["event_id"] = result.get("id")
        if "workout_doc" in event:
            spec["workout_doc"] = event["workout_doc"]

    gcal_creds_json = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
    gcal_calendar_id = os.environ.get("CALENDAR_ID", "").strip()
    if gcal_creds_json and gcal_calendar_id:
        log.info("Google Agenda events aanmaken...")
        _gcal_push(specs, gcal_calendar_id, gcal_creds_json, ctx.get("running_plan", {}))
    else:
        log.info("GOOGLE_CREDENTIALS / CALENDAR_ID niet ingesteld — Google Agenda sync overgeslagen")

    _save_plan_to_gist(gist_id, github_token, specs, week_number)

    ical = _generate_ical(specs)
    _save_ical_to_gist(gist_id, github_token, ical)

    _notify(specs)

    log.info("Klaar! %d workout(s) gepland in intervals.icu.", len(specs))


if __name__ == "__main__":
    main()
