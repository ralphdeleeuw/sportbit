#!/usr/bin/env python3
"""
review_running_workout.py — Beoordeelt en past lopende workouts aan.

Modi (automatisch gedetecteerd of via --mode):
  auto   (default): detecteer automatisch welke modus van toepassing is
  daily:            dagelijkse review van aankomende workouts (1x per dag)
  prerun:           pre-run check vlak voor de run (met Pushover-notificatie)

Modus-detectie (bij 'auto'):
  1. Is er een run gepland binnen [90, 150] minuten van nu (AMS)? → prerun
  2. Is het 07:00-10:00 AMS én is last_daily_review niet vandaag? → daily
  3. Anders: niets doen (exit 0)
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

from generate_running_workout import (
    AMS,
    INTERVALS_BASE,
    _build_description,
    _build_intervals_event,
    _build_workout_doc,
    _cancelled_cf_dates,
    _delete_old_intervals_events,
    _load_gist,
    _parse_json,
    _push_to_intervals,
    _save_to_gist,
    _signed_up_cf_dates,
    _strip_html,
)

log = logging.getLogger(__name__)

_REVIEW_SYSTEM_PROMPT = """You are a professional running coach reviewing upcoming workouts for Ralph de Leeuw.
- 47 years old, 77kg, CrossFit 5x/week, runs 2x/week
- Current 5K: ~28 min (5:36/km) | Goal: 26 min (5:12/km)

Your task: evaluate the planned workout(s) and decide if any need adjustment based on:
- Recovery: HRV, resting HR, sleep, TSB (Training Stress Balance)
- CrossFit load same day or day before (especially heavy metcon or strength)
- Other planned physical activities nearby (mountain biking, etc.) — check "Other planned activities" section
- Nutrition: energy availability from MFP data
- Subjective health notes

Adjust DOWN when:
- HRV < 35ms or significantly below recent baseline
- TSB < -20 combined with poor sleep (< 6h) or high subjective fatigue
- Heavy CrossFit session same day AND run is later that day
- Athlete notes indicating illness, injury, or extreme fatigue

Adjust UP when:
- HRV above recent average AND TSB positive or near 0 AND good sleep
- No CrossFit same day, good nutrition, athlete notes indicate feeling good

Do NOT adjust for:
- Minor HRV/sleep variation within normal range
- TSB between -5 and -20 (normal productive training load)
- Slight fatigue without multiple confirming signals

Most workouts should stay unchanged. Only adjust when the evidence is clear.

Pace zones for reference:
- Conversational (max): 6:40/km
- Aerobic: 6:00-6:20/km
- Threshold: 5:45-5:55/km
- 5K current: 5:30-5:42/km
- Interval 400m: 5:10-5:25/km
- Interval 300m: 5:20-5:35/km
- Interval 200m: 5:00-5:15/km

Output: return ONLY valid JSON (no markdown, no explanation):
{
  "adjusted": true|false,
  "reason": "1-2 sentences explaining the decision",
  "workouts": [
    {
      "date": "YYYY-MM-DD",
      "session": "speed|long_run",
      "type": "easy_run|fartlek|interval_run|progressive_run|tempo_run",
      "name": "Short English session name",
      "description": "1-2 sentences about the goal",
      "total_distance_km": <float>,
      "steps": [<steps — see format below>]
    }
  ]
}

Step formats:
  Warm-up:      {"type":"warmup",   "distance_m":<int>, "pace_max":"M:SS"}
  Easy/long run:{"type":"run",      "distance_m":<int>, "pace_max":"M:SS"}
  Interval:     {"type":"run",      "distance_m":<int>, "pace_target":"M:SS"}
  Repeat:       {"type":"repeat",   "count":<int>, "children":[<steps>]}
  Walking rest: {"type":"rest",     "duration_s":<int>}
  Cool-down:    {"type":"cooldown", "distance_m":<int>, "pace_max":"M:SS"}

If no adjustments needed: {"adjusted": false, "reason": "...", "workouts": []}"""


# ── Data laden ────────────────────────────────────────────────────────────────

def _load_review_context(gist_id: str, token: str) -> dict:
    files = _load_gist(gist_id, token)

    plan = _parse_json(files.get("running_plan.json", ""), "running_plan.json") or {}
    wod_data = _parse_json(files.get("sugarwod_wod.json", ""), "sugarwod_wod.json") or {}
    health_input = _parse_json(files.get("health_input.json", ""), "health_input.json") or {}
    mfp_data = _parse_json(files.get("myfitnesspal_nutrition.json", ""), "myfitnesspal_nutrition.json") or {}

    personal_events_raw = files.get("personal_events.json", "")
    personal_events_data = _parse_json(personal_events_raw, "personal_events.json") or {}
    personal_events: list[dict] = (
        personal_events_data.get("events", [])
        if isinstance(personal_events_data, dict)
        else []
    )

    intervals_data = wod_data.get("intervals_data") or {}
    all_wods: list[dict] = wod_data.get("workouts") or []
    activities_by_date: dict = intervals_data.get("activities", {}).get("by_date", {})
    today_str = date.today().isoformat()
    cutoff_upcoming = (date.today() + timedelta(days=10)).isoformat()

    # Upcoming personal events binnen planningshorizon
    upcoming_personal_events = [
        e for e in personal_events
        if today_str <= e.get("date", "") <= cutoff_upcoming
    ]

    # Recent CrossFit: gebruik intervals.icu activiteiten (daadwerkelijk bijgewoond)
    cf_activity_types = {"crossfit", "weight", "strength", "hiit", "weighttraining"}
    cutoff_recent = (date.today() - timedelta(days=14)).isoformat()
    wods_by_date: dict[str, dict] = {w.get("date", ""): w for w in all_wods if w.get("date")}
    recent_cf_from_intervals: dict[str, dict] = {}
    for d, acts in activities_by_date.items():
        if not (cutoff_recent <= d < today_str):
            continue
        cf_acts = [a for a in acts if any(t in (a.get("type") or "").lower() for t in cf_activity_types)]
        if not cf_acts:
            continue
        entry = dict(wods_by_date.get(d, {"date": d}))
        act = cf_acts[0]
        if act.get("duration_min"):
            entry["duration_min"] = act["duration_min"]
        if act.get("avg_hr"):
            entry["avg_hr"] = act["avg_hr"]
        tl = act.get("training_load") or act.get("trimp")
        if tl is not None:
            entry["training_load"] = tl
        recent_cf_from_intervals[d] = entry

    return {
        "running_plan": plan,
        "wellness": intervals_data.get("wellness", {}).get("by_date", {}),
        "activities": activities_by_date,
        "health_input": health_input,
        "all_wods": all_wods,
        "recent_cf_by_date": recent_cf_from_intervals,
        "cancelled_cf_dates": _cancelled_cf_dates(files),
        "signed_up_cf_dates": _signed_up_cf_dates(files),
        "mfp_by_date": (mfp_data.get("diary") or {}).get("by_date") or {},
        "today_str": today_str,
        "personal_events": upcoming_personal_events,
    }


# ── Modus-detectie ────────────────────────────────────────────────────────────

def _upcoming_workouts(plan: dict) -> list[dict]:
    today_str = date.today().isoformat()
    return [
        w for w in plan.get("workouts", [])
        if w.get("date", "") >= today_str and not w.get("completed")
    ]


def _workout_start_dt(workout: dict) -> datetime | None:
    d = workout.get("date", "")
    t = workout.get("time", "20:00" if workout.get("session") == "speed" else "09:00")
    try:
        return datetime.fromisoformat(f"{d}T{t}").replace(tzinfo=AMS)
    except ValueError:
        return None


def _detect_prerun_workout(workouts: list[dict]) -> dict | None:
    now = datetime.now(AMS)
    for w in workouts:
        dt = _workout_start_dt(w)
        if dt is None:
            continue
        minutes_until = (dt - now).total_seconds() / 60
        if 90 <= minutes_until <= 150:
            return w
    return None


def _detect_mode(mode_arg: str, workouts: list[dict], plan: dict) -> str:
    if mode_arg in ("daily", "prerun"):
        return mode_arg

    if _detect_prerun_workout(workouts):
        return "prerun"

    now_ams = datetime.now(AMS)
    if 7 <= now_ams.hour < 10:
        last_review = plan.get("last_daily_review", "")
        if last_review != date.today().isoformat():
            return "daily"

    return "none"


# ── Context bouwen voor Claude ────────────────────────────────────────────────

def _format_steps_brief(steps: list[dict], indent: str = "  ") -> list[str]:
    lines = []
    for s in steps:
        stype = s.get("type")
        if stype in ("warmup", "cooldown"):
            dist = s.get("distance_m", "")
            pace = s.get("pace_max", "")
            label = "Warmup" if stype == "warmup" else "Cooldown"
            dist_str = f"{dist/1000:.1f}km " if dist else ""
            pace_str = f" (max {pace}/km)" if pace else ""
            lines.append(f"{indent}{dist_str}{label}{pace_str}")
        elif stype == "run":
            dist = s.get("distance_m")
            pace = s.get("pace_target") or s.get("pace_max")
            pace_str = f" @ {pace}/km" if s.get("pace_target") else (f" (max {pace}/km)" if pace else "")
            lines.append(f"{indent}{dist}m{pace_str}" if dist else f"{indent}run{pace_str}")
        elif stype == "rest":
            lines.append(f"{indent}{s.get('duration_s', '?')}s walking rest")
        elif stype == "repeat":
            lines.append(f"{indent}{s['count']}x:")
            lines.extend(_format_steps_brief(s.get("children", []), indent + "  "))
    return lines


def _build_review_context(
    mode: str,
    target_workouts: list[dict],
    wellness_by_date: dict,
    all_wods: list[dict],
    mfp_by_date: dict,
    health_input: dict,
    activities_by_date: dict | None = None,
    cancelled_cf_dates: set[str] = frozenset(),
    signed_up_cf_dates: set[str] = frozenset(),
    recent_cf_by_date: dict | None = None,
    personal_events: list[dict] | None = None,
) -> str:
    now_ams = datetime.now(AMS)
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    dag_nl = ["ma", "di", "wo", "do", "vr", "za", "zo"]

    sections = [
        f"Today: {today_str} ({dag_nl[date.today().weekday()]}), {now_ams.strftime('%H:%M')} AMS",
    ]

    # Workouts te beoordelen
    if mode == "prerun":
        w = target_workouts[0]
        dt = _workout_start_dt(w)
        min_until = int((dt - now_ams).total_seconds() / 60) if dt else "?"
        sections.append(
            f"Mode: PRE-RUN — run starts at {w.get('time', '?')} AMS (in ~{min_until} min)"
        )
    else:
        sections.append("Mode: DAILY REVIEW — assess all upcoming workouts")

    wod_section_lines = ["Workout(s) to review:"]
    for w in target_workouts:
        wod_section_lines.append(
            f"  [{w.get('session', '?')}] {w.get('date')} {w.get('time', '')} — "
            f"{w.get('name', '?')} ({w.get('total_distance_km', '?')}km)"
        )
        if w.get("description"):
            wod_section_lines.append(f"    Goal: {w['description']}")
        steps = w.get("steps") or (w.get("workout_doc") or {}).get("steps") or []
        if steps:
            wod_section_lines.extend(_format_steps_brief(steps, "    "))
    sections.append("\n".join(wod_section_lines))

    # Wellness (laatste 5 dagen)
    wellness_lines = []
    for d in sorted(wellness_by_date.keys(), reverse=True)[:5]:
        ww = wellness_by_date[d]
        parts = [f"  {d}:"]
        if ww.get("hrv"):             parts.append(f"HRV={ww['hrv']}ms")
        if ww.get("hrv_sdnn"):        parts.append(f"SDNN={ww['hrv_sdnn']}ms")
        if ww.get("resting_hr"):      parts.append(f"resting_hr={ww['resting_hr']}bpm")
        if ww.get("avg_sleeping_hr"): parts.append(f"sleep_hr={ww['avg_sleeping_hr']:.0f}bpm")
        if ww.get("readiness") is not None: parts.append(f"readiness={ww['readiness']}")
        if ww.get("sleep_hrs"):       parts.append(f"sleep={ww['sleep_hrs']}h")
        if ww.get("sleep_score") is not None: parts.append(f"sleep_score={ww['sleep_score']}")
        if ww.get("respiration") is not None: parts.append(f"resp={ww['respiration']:.1f}/min")
        if ww.get("spo2") is not None:  parts.append(f"SpO2={ww['spo2']}%")
        if ww.get("ctl") is not None:   parts.append(f"CTL={ww['ctl']:.0f}")
        if ww.get("atl") is not None:   parts.append(f"ATL={ww['atl']:.0f}")
        if ww.get("tsb") is not None:   parts.append(f"TSB={ww['tsb']:+.0f}")
        wellness_lines.append(" ".join(parts))
    if wellness_lines:
        sections.append("Recovery data (last 5 days):\n" + "\n".join(wellness_lines))
    else:
        sections.append("Recovery data: not available")

    # Recente hardloopactiviteiten (laatste 14 dagen, via intervals.icu)
    run_types = {"run", "running", "jog", "trailrun", "treadmill"}
    acts_by_date = activities_by_date or {}
    run_lines = []
    for d in sorted(acts_by_date.keys(), reverse=True)[:14]:
        for act in acts_by_date.get(d, []):
            if not any(rt in (act.get("type") or "").lower() for rt in run_types):
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
            if act.get("avg_cadence"):
                parts.append(f"cadence {round(act['avg_cadence'] * 2)}spm")
            if act.get("rpe"):
                parts.append(f"RPE {act['rpe']}")
            tl = act.get("training_load") or act.get("trimp")
            if tl is not None:
                parts.append(f"TL {round(tl)}")
            run_lines.append(" ".join(parts))
            hz = act.get("hr_zone_times")
            if hz and isinstance(hz, list) and sum(hz) > 0:
                total = sum(hz)
                zone_str = " ".join(
                    f"Z{i+1}:{round(v/total*100)}%"
                    for i, v in enumerate(hz[:5]) if v > 0
                )
                run_lines.append(f"    HR zones: {zone_str}")
            for i, lap in enumerate(act.get("laps", []), 1):
                lp = [f"    lap {i}:"]
                if lap.get("distance_m"): lp.append(f"{lap['distance_m']}m")
                if lap.get("pace_per_km"): lp.append(f"{lap['pace_per_km']}/km")
                if lap.get("avg_hr"):     lp.append(f"HR {lap['avg_hr']}bpm")
                if lap.get("avg_cadence"): lp.append(f"cadence {round(lap['avg_cadence'] * 2)}spm")
                run_lines.append(" ".join(lp))
    if run_lines:
        sections.append("Recent running activities (last 14 days):\n" + "\n".join(run_lines))

    # CrossFit sessions relevant voor de run(s) — gebruik ingeschreven sessies
    run_dates = {w.get("date", "") for w in target_workouts}
    cf_dates = run_dates | {
        (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        for d in run_dates if d
    }
    wods_by_date = {w.get("date", ""): w for w in all_wods if w.get("date")}
    relevant_cf_dates = [
        d for d in cf_dates
        if d not in cancelled_cf_dates
        and (d in signed_up_cf_dates or d in wods_by_date)
    ]
    if relevant_cf_dates:
        cf_lines = []
        for d in sorted(relevant_cf_dates):
            wod = wods_by_date.get(d, {"date": d})
            title = wod.get("title") or wod.get("name") or "CrossFit"
            desc = _strip_html(wod.get("description") or "")[:120]
            notes = wod.get("athlete_notes") or ""
            label = "same day as run" if d in run_dates else "day before run"
            signed = " [signed up]" if d in signed_up_cf_dates else ""
            # Voeg interval.icu data toe als beschikbaar (dag van/voor de run)
            cf_act = (recent_cf_by_date or {}).get(d, {})
            line = f"  {d} ({label}){signed} — {title}"
            if desc:
                line += f"\n    {desc}"
            if cf_act.get("avg_hr"):
                line += f"\n    Actual: avg HR {cf_act['avg_hr']}bpm"
                if cf_act.get("duration_min"):
                    line += f", {cf_act['duration_min']}min"
                tl = cf_act.get("training_load")
                if tl is not None:
                    line += f", TL {round(tl)}"
            if notes:
                line += f"\n    Your notes: {notes[:80]}"
            cf_lines.append(line)
        sections.append("CrossFit sessions (same day or day before run):\n" + "\n".join(cf_lines))
    else:
        sections.append("CrossFit on run day / day before: none scheduled")

    # Upcoming personal events (mountainbike, etc.)
    if personal_events:
        dag_nl = ["ma", "di", "wo", "do", "vr", "za", "zo"]
        pe_lines = []
        for e in sorted(personal_events, key=lambda x: x.get("date", "")):
            d = e.get("date", "")
            try:
                dag = dag_nl[date.fromisoformat(d).weekday()]
            except ValueError:
                dag = ""
            title = e.get("title", "Activiteit")
            line = f"  {d} ({dag}) — {title}"
            if e.get("time"):
                line += f" om {e['time']}"
            if e.get("notes"):
                line += f" — {e['notes'][:80]}"
            pe_lines.append(line)
        sections.append(
            "Other planned activities (consider recovery — avoid hard run the day before):\n"
            + "\n".join(pe_lines)
        )

    # MFP voeding (laatste 3 dagen)
    mfp_lines = []
    for d in sorted(mfp_by_date.keys(), reverse=True)[:3]:
        m = mfp_by_date[d]
        cal = m.get("calories", 0)
        if not cal:
            continue
        prot = round(m.get("protein_g") or 0)
        carbs = round(m.get("carbs_g") or 0)
        fat = round(m.get("fat_g") or 0)
        mfp_lines.append(f"  {d}: {cal} kcal, {prot}g protein, {carbs}g carbs, {fat}g fat")
    if mfp_lines:
        sections.append("Nutrition last 3 days (MyFitnessPal):\n" + "\n".join(mfp_lines))

    # Subjectieve notities
    health_lines = [
        f"  - {k}: {v}"
        for k, v in health_input.items()
        if k not in ("date", "run_1", "run_2")
    ]
    if health_lines:
        sections.append("Subjective health notes:\n" + "\n".join(health_lines))

    return "\n\n".join(sections)


# ── Claude aanroepen ──────────────────────────────────────────────────────────

def _review_with_claude(context_text: str) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=_REVIEW_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": "Review the following workout(s) and return your decision:\n\n" + context_text,
        }],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:].lstrip()
    return json.loads(raw)


# ── Aanpassingen doorvoeren ───────────────────────────────────────────────────

def _apply_adjustments(
    review: dict,
    original_workouts: list[dict],
    plan: dict,
    athlete_id: str,
    api_key: str,
    gist_id: str,
    github_token: str,
) -> list[dict]:
    adjusted_specs = review.get("workouts", [])
    if not adjusted_specs:
        return original_workouts

    updated = list(plan.get("workouts", []))

    for adj in adjusted_specs:
        adj_date = adj.get("date", "")
        # Zoek originele workout op datum
        orig = next((w for w in original_workouts if w.get("date") == adj_date), None)
        if orig is None:
            log.warning("Aanpassing voor onbekende datum %s — overgeslagen", adj_date)
            continue

        # Bewaar meta-velden van het origineel
        adj.setdefault("time", orig.get("time", "20:00" if adj.get("session") == "speed" else "09:00"))
        adj.setdefault("week_number", orig.get("week_number"))
        adj["full_description"] = _build_description(adj)

        # Verwijder oud intervals.icu event voor deze workout
        old_event_id = orig.get("event_id")
        if old_event_id:
            try:
                session = requests.Session()
                session.auth = ("API_KEY", api_key)
                resp = session.delete(f"{INTERVALS_BASE}/{athlete_id}/events/{old_event_id}", timeout=20)
                if resp.ok:
                    log.info("Oud event %s verwijderd voor %s", old_event_id, adj_date)
                else:
                    log.warning("Kon oud event %s niet verwijderen: %s", old_event_id, resp.status_code)
            except Exception as exc:
                log.warning("Fout bij verwijderen event %s: %s", old_event_id, exc)

        # Maak nieuw intervals.icu event
        event = _build_intervals_event(adj)
        results = _push_to_intervals(athlete_id, api_key, [event])
        if results and results[0]:
            adj["event_id"] = results[0].get("id")
            if "workout_doc" in event:
                adj["workout_doc"] = event["workout_doc"]

        # Vervang in plan
        for i, w in enumerate(updated):
            if w.get("date") == adj_date:
                updated[i] = adj
                break

    # Sla bijgewerkt plan op
    plan["workouts"] = updated
    _save_to_gist(gist_id, github_token, "running_plan.json",
                  json.dumps(plan, indent=2, ensure_ascii=False))
    log.info("running_plan.json bijgewerkt na review-aanpassing")
    return [adj for adj in updated if adj.get("date") in {w.get("date") for w in original_workouts}]


def _notify(
    mode: str,
    workouts: list[dict],
    adjusted: bool,
    reason: str,
) -> None:
    dag_nl = ["ma", "di", "wo", "do", "vr", "za", "zo"]

    if mode == "prerun":
        w = workouts[0]
        d = datetime.strptime(w["date"], "%Y-%m-%d")
        dag = dag_nl[d.weekday()]
        time_str = w.get("time", "?")
        dist = w.get("total_distance_km", "?")
        title = f"Hardlopen over ~2u: {w['name']} ({dist}km)"

        lines = [f"{dag} {d.day}/{d.month} {time_str}"]
        steps = w.get("steps") or (w.get("workout_doc") or {}).get("steps") or []
        lines.extend(_format_steps_brief(steps))

        if adjusted:
            lines.append(f"\nAanpassing: {reason}")

        msg = "\n".join(lines)

    else:
        if not adjusted:
            return
        title = "Hardloopplan bijgesteld 🏃"
        lines = [f"Reden: {reason}", ""]
        for w in workouts:
            d = datetime.strptime(w["date"], "%Y-%m-%d")
            dag = dag_nl[d.weekday()]
            dist = w.get("total_distance_km", "?")
            lines.append(f"{dag} {d.day}/{d.month} — {w['name']} ({dist}km)")
        msg = "\n".join(lines)

    notify.send_notification(title, msg)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    mode_arg = "auto"
    for arg in sys.argv[1:]:
        if arg.startswith("--mode="):
            mode_arg = arg.split("=", 1)[1]
        elif arg == "--mode" and sys.argv.index(arg) + 1 < len(sys.argv):
            mode_arg = sys.argv[sys.argv.index(arg) + 1]

    athlete_id   = os.environ.get("INTERVALS_ATHLETE_ID", "").strip()
    api_key      = os.environ.get("INTERVALS_API_KEY", "").strip()
    gist_id      = os.environ.get("GIST_ID", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()

    missing = [n for n, v in [
        ("INTERVALS_ATHLETE_ID", athlete_id),
        ("INTERVALS_API_KEY", api_key),
        ("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")),
        ("GIST_ID", gist_id),
        ("GITHUB_TOKEN", github_token),
    ] if not v]
    if missing:
        log.error("Vereiste environment variables ontbreken: %s", ", ".join(missing))
        sys.exit(1)

    log.info("Data laden uit Gist...")
    ctx = _load_review_context(gist_id, github_token)
    plan = ctx["running_plan"]
    upcoming = _upcoming_workouts(plan)

    if not upcoming:
        log.info("Geen aankomende workouts gevonden — niets te doen")
        sys.exit(0)

    mode = _detect_mode(mode_arg, upcoming, plan)
    log.info("Modus: %s", mode)

    if mode == "none":
        log.info("Geen actie vereist op dit moment")
        sys.exit(0)

    if mode == "prerun":
        target = _detect_prerun_workout(upcoming)
        if target is None and mode_arg == "prerun":
            # Handmatig prerun gevraagd: gebruik eerstvolgende workout
            target = upcoming[0]
        if target is None:
            log.info("Geen run in prerun-venster gevonden — exit")
            sys.exit(0)
        target_workouts = [target]
    else:
        target_workouts = upcoming

    log.info("Workouts te beoordelen: %d", len(target_workouts))

    context_text = _build_review_context(
        mode=mode,
        target_workouts=target_workouts,
        wellness_by_date=ctx["wellness"],
        all_wods=ctx["all_wods"],
        mfp_by_date=ctx["mfp_by_date"],
        health_input=ctx["health_input"],
        activities_by_date=ctx.get("activities"),
        cancelled_cf_dates=ctx.get("cancelled_cf_dates", frozenset()),
        signed_up_cf_dates=ctx.get("signed_up_cf_dates", frozenset()),
        recent_cf_by_date=ctx.get("recent_cf_by_date"),
        personal_events=ctx.get("personal_events"),
    )
    log.info("Review context:\n%s", context_text)

    log.info("Claude raadplegen voor review...")
    review = _review_with_claude(context_text)
    log.info("Claude: adjusted=%s — %s", review.get("adjusted"), review.get("reason", ""))

    adjusted = bool(review.get("adjusted"))
    reason = review.get("reason", "")

    if adjusted:
        log.info("Aanpassingen doorvoeren...")
        target_workouts = _apply_adjustments(
            review=review,
            original_workouts=target_workouts,
            plan=plan,
            athlete_id=athlete_id,
            api_key=api_key,
            gist_id=gist_id,
            github_token=github_token,
        )
    else:
        # Markeer dagelijkse review als gedaan (ook als er geen aanpassing was)
        if mode == "daily":
            plan["last_daily_review"] = date.today().isoformat()
            _save_to_gist(gist_id, github_token, "running_plan.json",
                          json.dumps(plan, indent=2, ensure_ascii=False))

    # last_daily_review bijwerken na succesvolle daily review
    if mode == "daily" and adjusted:
        plan["last_daily_review"] = date.today().isoformat()
        _save_to_gist(gist_id, github_token, "running_plan.json",
                      json.dumps(plan, indent=2, ensure_ascii=False))

    _notify(mode, target_workouts, adjusted, reason)
    log.info("Klaar.")


if __name__ == "__main__":
    main()
