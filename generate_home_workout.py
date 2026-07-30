#!/usr/bin/env python3
"""
generate_home_workout.py — Genereert een gepersonaliseerd dagelijks thuistraining plan
op basis van herstelstatus, recente activiteiten en komende sessies.

Werking:
  1. Haalt alle fitnessdata op uit de GitHub Gist.
  2. Berekent de huidige week van het squat-progressieschema.
  3. Vraagt Claude AI om een volledig gepersonaliseerd plan.
  4. Slaat het resultaat op als home_workout_plan.json in de Gist.

Environment variables:
  GIST_ID           — GitHub Gist ID (vereist)
  GITHUB_TOKEN      — GitHub token met gist scope (vereist)
  ANTHROPIC_API_KEY — Claude API key (vereist)
  VAPID_PRIVATE_KEY / VAPID_CLAIMS_EMAIL — voor Web Push notificaties (optioneel)
  TARGET_DATE       — datum YYYY-MM-DD (optioneel, standaard vandaag)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import anthropic

import notify
from gist_utils import load_gist, patch_gist
from injuries import format_injuries_prompt, parse_injuries

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

AMS = ZoneInfo("Europe/Amsterdam")
GIST_FILENAME = "home_workout_plan.json"
# Kostenbesparing: Haiku 4.5 ($1/$5 per 1M tokens) i.p.v. Opus ($5/$25). De
# thuistraining is een eenvoudige, gestructureerde dag-routine — ruim binnen Haiku's
# kunnen. Verhoog naar claude-sonnet-4-6 of claude-opus-4-8 als de kwaliteit tegenvalt.
MODEL = "claude-haiku-4-5"
DAY_NL = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]

# ── Squat progressieschema — EXACT gespiegeld van HOME_WORKOUT.squat_progression in app.js ──
# BELANGRIJK: HOME_WORKOUT.start_date in app.js (regel 312) moet synchroon blijven met START_DATE hier.
HOME_WORKOUT_START_DATE = "2026-04-28"

SQUAT_PROGRESSION = [
    {"from_week":  1, "variant": "bw",           "label": "Bodyweight Squats",    "sub": "",        "sets": 1, "reps": 20},
    {"from_week":  5, "variant": "goblet_12kg",   "label": "Goblet Squat",         "sub": "KB 12kg", "sets": 1, "reps": 20},
    {"from_week":  9, "variant": "goblet_2x12",   "label": "Goblet Squat",         "sub": "KB 12kg", "sets": 2, "reps": 12},
    {"from_week": 13, "variant": "db_goblet_12",  "label": "Goblet Squat",         "sub": "DB 12kg", "sets": 2, "reps": 15},
    {"from_week": 17, "variant": "db_goblet_16",  "label": "Goblet Squat",         "sub": "DB 16kg", "sets": 2, "reps": 12},
    {"from_week": 21, "variant": "db_front_2x8",  "label": "DB Front Squat",       "sub": "2×8kg",   "sets": 3, "reps": 10},
    {"from_week": 25, "variant": "db_front_2x12", "label": "DB Front Squat",       "sub": "2×12kg",  "sets": 3, "reps": 8 },
    {"from_week": 29, "variant": "db_lunge_2x8",  "label": "DB Alternating Lunge", "sub": "2×8kg",   "sets": 3, "reps": 10},
    {"from_week": 33, "variant": "db_front_2x16", "label": "DB Front Squat",       "sub": "2×16kg",  "sets": 3, "reps": 6 },
]

# Mobility catalogus — EXACT gespiegeld van MOBILITY_CATALOG in app.js
MOBILITY_CATALOG = [
    {"id": "mob_hip_flexor",   "name": "Heupbuiger Stretch",        "duration": "45s/kant"},
    {"id": "mob_pigeon",       "name": "Duif Pose (Pigeon)",         "duration": "60s/kant"},
    {"id": "mob_ankle",        "name": "Enkel Mobiliteit",           "duration": "10r/kant"},
    {"id": "mob_quad",         "name": "Quad Stretch (staand)",      "duration": "45s/kant"},
    {"id": "mob_glute_bridge", "name": "Glute Bridge",               "duration": "15 reps" },
    {"id": "mob_chest",        "name": "Deurpost Borststretch",      "duration": "30s/kant"},
    {"id": "mob_shoulder",     "name": "Schouder Openingsstretch",   "duration": "30s/kant"},
    {"id": "mob_wrist",        "name": "Pols Mobiliteit",            "duration": "1 min"   },
    {"id": "mob_lat",          "name": "Lat Stretch aan Deur",       "duration": "30s/kant"},
    {"id": "mob_hamstring",    "name": "Hamstring Stretch",          "duration": "45s/kant"},
    {"id": "mob_cat_cow",      "name": "Cat-Cow",                    "duration": "10 reps" },
    {"id": "mob_thoracic",     "name": "Thoracale Rotatie",          "duration": "10r/kant"},
    {"id": "mob_calf",         "name": "Kuit Stretch",               "duration": "45s/kant"},
    {"id": "mob_t_spine",      "name": "Foam Roller Ruggengraat",    "duration": "1 min"   },
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_json(raw: str, label: str) -> dict | list | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("%s is geen geldig JSON: %s", label, exc)
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _get_target_date() -> date:
    raw = os.environ.get("TARGET_DATE", "").strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            log.warning("Ongeldige TARGET_DATE '%s' — gebruik vandaag.", raw)
    return date.today()


def _get_program_week(target: date) -> int:
    start = date.fromisoformat(HOME_WORKOUT_START_DATE)
    days = (target - start).days
    return max(1, days // 7 + 1)


def _get_squat_variant(week: int) -> dict:
    chosen = SQUAT_PROGRESSION[0]
    for step in SQUAT_PROGRESSION:
        if week >= step["from_week"]:
            chosen = step
        else:
            break
    return chosen


# ── Fitnessdata laden ──────────────────────────────────────────────────────────

def _load_fitness_data(files: dict[str, str]) -> dict:
    wod_data = _parse_json(files.get("sugarwod_wod.json", ""), "sugarwod_wod.json") or {}
    health_input_raw = _parse_json(files.get("health_input.json", ""), "health_input.json") or {}
    running_plan_raw = _parse_json(files.get("running_plan.json", ""), "running_plan.json") or {}
    personal_events_raw = _parse_json(files.get("personal_events.json", ""), "personal_events.json") or {}
    hw_log_raw = _parse_json(files.get("home_workout_log.json", ""), "home_workout_log.json") or {}
    state_raw = _parse_json(files.get("sportbit_state.json", ""), "sportbit_state.json") or {}

    intervals_data = wod_data.get("intervals_data") or {}
    strava_data = wod_data.get("strava_data") or {}

    # Ingeschreven CrossFit-datums
    cancelled_ids = set(state_raw.get("cancelled", {}).keys())
    signed_up_dates: set[str] = {
        info["date"]
        for eid, info in state_raw.get("signed_up", {}).items()
        if eid not in cancelled_ids and info.get("date")
    }

    # Thuistraining logboek: [{date, exercises_done, mobility_done, squat_variant, notes}]
    hw_log_entries: list[dict] = sorted(
        hw_log_raw.get("entries", []),
        key=lambda e: e.get("date", ""),
        reverse=True,
    )

    return {
        "wod_by_date": wod_data.get("by_date") or {},
        "wellness": intervals_data.get("wellness", {}).get("by_date", {}),
        "activities": intervals_data.get("activities", {}).get("by_date", {}),
        "strava": strava_data.get("activities_by_date") or {},
        "health_input": health_input_raw,
        "health_history": health_input_raw.get("history", []),
        "running_plan_workouts": running_plan_raw.get("workouts") or [],
        "personal_events": personal_events_raw.get("events") or [],
        "home_workout_log": hw_log_entries,
        "signed_up_dates": signed_up_dates,
        "withings_data": wod_data.get("withings_data"),
        "strava_data": strava_data,
        "intervals_data": intervals_data,
    }


# ── Context bouwen voor Claude ─────────────────────────────────────────────────

def _dedup_activities(day_acts: list[dict]) -> list[dict]:
    seen: list[tuple] = []
    result: list[dict] = []
    for act in day_acts:
        dur = round(act.get("duration_min") or 0)
        act_type = (act.get("type") or "").lower()
        key = (act_type, dur // 5)
        if key not in seen:
            seen.append(key)
            result.append(act)
    return result


def _build_context(data: dict, target: date, week: int, squat: dict) -> str:
    today = target
    sections: list[str] = []

    dag_naam = DAY_NL[today.weekday()]
    sections.append(
        f"Datum: {today.isoformat()} ({dag_naam})\n"
        f"Programmaweek: {week}\n"
        f"Huidig squat schema: {squat['label']}"
        + (f" ({squat['sub']})" if squat["sub"] else "")
        + f" — {squat['sets']} set(s) × {squat['reps']} reps (standaard, aanpassing mogelijk)"
    )

    # ── Actieve blessures (health_input.json) ─────────────────────────────────
    injury_block = format_injuries_prompt(parse_injuries(data.get("health_input")), lang="nl")
    if injury_block:
        sections.append(injury_block.strip())

    # ── Wellness afgelopen 7 dagen ─────────────────────────────────────────────
    wellness: dict = data["wellness"]
    recent_w_dates = sorted(wellness.keys(), reverse=True)[:7]
    if recent_w_dates:
        w_lines = []
        for d_str in recent_w_dates:
            w = wellness[d_str]
            parts = [f"  {d_str}:"]
            if w.get("hrv") is not None:        parts.append(f"HRV={w['hrv']}ms")
            if w.get("resting_hr") is not None:  parts.append(f"rustpols={w['resting_hr']}bpm")
            if w.get("sleep_hrs") is not None:   parts.append(f"slaap={w['sleep_hrs']}u")
            if w.get("sleep_score") is not None: parts.append(f"slaapscore={w['sleep_score']}")
            if w.get("ctl") is not None:         parts.append(f"CTL={w['ctl']}")
            if w.get("atl") is not None:         parts.append(f"ATL={w['atl']}")
            if w.get("tsb") is not None:         parts.append(f"TSB={w['tsb']}")
            if w.get("readiness") is not None:   parts.append(f"readiness={w['readiness']}")
            if w.get("spo2") is not None:        parts.append(f"SpO2={w['spo2']}%")
            w_lines.append(" ".join(parts))
        sections.append("Wellness & trainingsbelasting (laatste 7 dagen):\n" + "\n".join(w_lines))
    else:
        sections.append("Wellness data: niet beschikbaar")

    # ── Subjectieve scores ─────────────────────────────────────────────────────
    health_input: dict = data["health_input"]
    health_history: list = data["health_history"]
    all_health = []
    if health_input.get("date"):
        all_health.append(health_input)
    all_health.extend(health_history)
    all_health = sorted(all_health, key=lambda x: x.get("date", ""), reverse=True)[:5]
    if all_health:
        h_lines = []
        for h in all_health:
            parts = [f"  {h.get('date', '?')}:"]
            for k in ("slaap", "energie", "spierpijn", "stress"):
                v = h.get(k)
                if v is not None:
                    parts.append(f"{k}={v}/10")
            h_lines.append(" ".join(parts))
        sections.append("Subjectieve herstelscores (laatste 5 invoeren):\n" + "\n".join(h_lines))

    # ── Recente activiteiten (7 dagen) ─────────────────────────────────────────
    cutoff_7 = (today - timedelta(days=7)).isoformat()
    acts_by_date: dict = data["activities"]
    strava_by_date: dict = data["strava"]
    all_act_dates = sorted(
        set(list(acts_by_date.keys()) + list(strava_by_date.keys())),
        reverse=True,
    )
    recent_act_dates = [d_str for d_str in all_act_dates if d_str >= cutoff_7]

    if recent_act_dates:
        act_lines = []
        for d_str in recent_act_dates:
            day_acts = _dedup_activities(
                acts_by_date.get(d_str, []) + strava_by_date.get(d_str, [])
            )
            for act in day_acts:
                name = act.get("name") or act.get("type") or "activiteit"
                dur = act.get("duration_min")
                avg_hr = act.get("avg_hr")
                tl = act.get("training_load") or act.get("suffer_score")
                act_type = act.get("type", "")
                parts = [f"  {d_str}: {name} ({act_type})"]
                if dur:
                    parts.append(f"{dur}min")
                if avg_hr:
                    parts.append(f"HR {avg_hr}bpm")
                if tl:
                    parts.append(f"TL {round(tl)}")
                hz = act.get("hr_zone_times")
                if hz and isinstance(hz, list) and sum(hz) > 0:
                    total = sum(hz)
                    zone_parts = [f"Z{i+1}:{round(v/total*100)}%" for i, v in enumerate(hz[:5]) if v > 0]
                    if zone_parts:
                        parts.append("zones=[" + " ".join(zone_parts) + "]")
                act_lines.append(" ".join(parts))
        sections.append("Recente activiteiten (afgelopen 7 dagen):\n" + "\n".join(act_lines))
    else:
        sections.append("Recente activiteiten: geen data beschikbaar")

    # ── CrossFit lessen bijgewoond (14 dagen) ─────────────────────────────────
    cutoff_14 = (today - timedelta(days=14)).isoformat()
    signed_up_dates: set[str] = data["signed_up_dates"]
    wod_by_date: dict = data["wod_by_date"]
    wod_lines = []
    for d_str in sorted(wod_by_date.keys(), reverse=True):
        if d_str < cutoff_14 or d_str > today.isoformat():
            continue
        if d_str not in signed_up_dates:
            continue
        for w in wod_by_date[d_str]:
            name = w.get("name") or w.get("title") or "WOD"
            desc = _strip_html(w.get("description") or "")[:150]
            line = f"  {d_str} — {name}"
            if desc:
                line += f": {desc}"
            wod_lines.append(line)
    if wod_lines:
        sections.append("CrossFit lessen bijgewoond (afgelopen 14 dagen):\n" + "\n".join(wod_lines))
    else:
        sections.append("CrossFit lessen bijgewoond (afgelopen 14 dagen): geen data")

    # ── Komende agenda: vandaag + 3 dagen ─────────────────────────────────────
    run_by_date: dict[str, dict] = {
        s["date"]: s for s in data.get("running_plan_workouts", []) if s.get("date")
    }
    events_by_date: dict[str, list] = {}
    for ev in data.get("personal_events", []):
        d_str = ev.get("date", "")
        if d_str:
            events_by_date.setdefault(d_str, []).append(ev)

    upcoming_lines = []
    for offset in range(0, 4):
        d = today + timedelta(days=offset)
        d_str = d.isoformat()
        dag = DAY_NL[d.weekday()]
        day_parts: list[str] = []

        if d_str in signed_up_dates:
            wods = wod_by_date.get(d_str, [])
            if wods:
                for w in wods:
                    name = w.get("name") or w.get("title") or "WOD"
                    desc = _strip_html(w.get("description") or "")[:150]
                    skill = _strip_html(w.get("skill_wod") or "")[:80]
                    strength = _strip_html(w.get("strength_wod") or "")[:80]
                    wod_text = f"CrossFit: {name}"
                    if desc:
                        wod_text += f" — {desc}"
                    if skill:
                        wod_text += f" | skill: {skill}"
                    if strength:
                        wod_text += f" | strength: {strength}"
                    day_parts.append(wod_text)
            else:
                day_parts.append("CrossFit (WOD nog niet bekend)")

        if d_str in run_by_date:
            run = run_by_date[d_str]
            run_name = run.get("name") or run.get("type") or "hardloopsessie"
            run_session = run.get("session") or ""
            run_dist = run.get("total_distance_km")
            run_dur = run.get("total_duration_min")
            run_text = f"Hardlopen: {run_name}"
            if run_session and run_session != run_name:
                run_text += f" ({run_session})"
            if run_dist:
                run_text += f" {run_dist}km"
            if run_dur:
                run_text += f" ~{run_dur}min"
            day_parts.append(run_text)

        for ev in events_by_date.get(d_str, []):
            ev_title = ev.get("title") or "Persoonlijk event"
            ev_notes = ev.get("notes") or ""
            ev_text = f"Event: {ev_title}"
            if ev_notes:
                ev_text += f" — {ev_notes[:80]}"
            day_parts.append(ev_text)

        label = "Vandaag" if offset == 0 else "Morgen" if offset == 1 else "Overmorgen" if offset == 2 else f"Over 3 dagen"
        if day_parts:
            upcoming_lines.append(f"  {label} ({d_str}, {dag}): " + " | ".join(day_parts))
        else:
            upcoming_lines.append(f"  {label} ({d_str}, {dag}): rustdag")

    sections.append("Komende agenda (vandaag + 3 dagen):\n" + "\n".join(upcoming_lines))

    # ── Laatste 7 thuistraining sessies ───────────────────────────────────────
    hw_log: list[dict] = data.get("home_workout_log", [])[:7]
    if hw_log:
        hw_lines = []
        for entry in hw_log:
            d_str = entry.get("date", "?")
            ex_done = ", ".join(entry.get("exercises_done") or []) or "–"
            mob_done = ", ".join(entry.get("mobility_done") or []) or "–"
            squat_v = entry.get("squat_variant") or "?"
            notes = entry.get("notes") or ""
            line = f"  {d_str}: oefeningen={ex_done} | squat={squat_v} | mobiliteit={mob_done}"
            if notes:
                line += f" | notitie: {notes[:80]}"
            hw_lines.append(line)
        sections.append("Laatste 7 thuistraining sessies:\n" + "\n".join(hw_lines))
    else:
        sections.append("Thuistraining logboek: geen eerdere sessies beschikbaar")

    # ── Squat progressieschema (volledig overzicht voor Claude) ───────────────
    prog_lines = []
    for step in SQUAT_PROGRESSION:
        current_marker = " ← HUIDIGE WEEK" if step["variant"] == squat["variant"] else ""
        prog_lines.append(
            f"  Vanaf week {step['from_week']:2d}: {step['label']}"
            + (f" ({step['sub']})" if step["sub"] else "")
            + f" — {step['sets']}×{step['reps']} reps{current_marker}"
        )
    sections.append("Volledig squat progressieschema:\n" + "\n".join(prog_lines))

    # ── Lichaamssamenstelling (Withings, optioneel) ────────────────────────────
    withings_data = data.get("withings_data")
    if withings_data and withings_data.get("measurements"):
        _m = withings_data["measurements"][0]
        w_lines = []
        if _m.get("weight_kg") is not None:  w_lines.append(f"  Gewicht: {_m['weight_kg']} kg")
        if _m.get("fat_pct") is not None:    w_lines.append(f"  Vetpercentage: {_m['fat_pct']}%")
        if _m.get("muscle_kg") is not None:  w_lines.append(f"  Spiermassa: {_m['muscle_kg']} kg")
        if w_lines:
            sections.append(f"Lichaamssamenstelling (Withings, {_m.get('date', '')}):\n" + "\n".join(w_lines))

    return "\n\n".join(sections)


# ── Claude prompt ──────────────────────────────────────────────────────────────

def _build_system_prompt(squat: dict) -> str:
    mobility_list = "\n".join(
        f'  - id: "{m["id"]}", name: "{m["name"]}", duration: "{m["duration"]}"'
        for m in MOBILITY_CATALOG
    )
    squat_label = squat["label"] + (f" ({squat['sub']})" if squat["sub"] else "")
    return f"""\
Jij bent een persoonlijke trainer en CrossFit coach die een dagelijkse thuistraining personaliseert voor Ralph de Leeuw (47 jaar, 77 kg, intermediate-advanced CrossFitter, CrossFit Hilversum).

De thuistraining bestaat ALTIJD uit deze vaste oefeningen in deze volgorde:
1. Pushups  (id: "pushup_1") — normaal 12 reps
2. Sit-ups  (id: "situp")    — normaal 25 reps
3. Pushups  (id: "pushup_2") — normaal 12 reps
4. Squat variant (id: "squat") — zie squat progressieschema in de context; HUIDIGE WEEK: {squat_label}, {squat['sets']}×{squat['reps']} reps
5. Pushups  (id: "pushup_3") — normaal 12 reps

TIJDSLIMIET — HARD CONSTRAINT: de TOTALE training (oefeningen + rust + mobiliteit) duurt MAXIMAAL 10 minuten.
Reken realistisch: elke pushup-set duurt ~25s uitvoering + 20s rust, sit-ups ~40s + 20s rust, squat set ~45s + 20s rust.
Geef estimated_duration_min altijd ≤10.

Regels voor de squat:
- Gebruik ALTIJD de squat-variant van de huidige week (nooit een week overslaan of een andere variant kiezen)
- Je MAG de reps/sets aanpassen (verminderen bij vermoeidheid)
- Geef het veld "variant" altijd de variant-code uit het schema (bijv. "goblet_2x12")

Jouw taak: pas de reps en mobility aan op basis van alle beschikbare data.

AANPASSINGSRICHTLIJNEN:
- ACTIEVE BLESSURE (blok "ACTIEVE BLESSURES" in de context) → dit gaat vóór alles. De vaste oefeningen liggen
  vast, maar verlaag de reps van elke oefening die het aangedane gebied belast fors (of tot een pijnvrij minimum)
  en zet in "adaptation_note" welk pijnvrij alternatief hij in plaats daarvan kan doen. Kies mobiliteit die de
  blessure ondersteunt en nooit provoceert. Benoem de blessure-aanpassing in de "coaching_note".
- Lage HRV (<35ms of <75% van gebruikelijk) of slechte slaap (<6u) → schakel terug naar 60-70% van de normale reps
- Hoge TSB (positief, goed uitgerust) → overweeg de volle reps of zelfs net iets meer
- Intensieve CrossFit gisteren (TL>80) of zware hardloopsessie → verlaag overlappende spiergroepen
- Squat/lunge/thruster vandaag of morgen → verlaag squat-reps met 30-40%
- Push/press/HSPU vandaag of morgen → verlaag pushup-reps met 30-40%
- Sport-event binnenkort → energie bewaren
- Prioriteit herstel → intensity_level "licht" met een korte maar duidelijke uitleg

MOBILITEITS-SELECTIE:
Kies precies 3 oefeningen (maximaal 4 als er echt urgente reden is) uit de onderstaande catalogus. Volgorde van prioriteit:
1. Meest urgent op basis van recente én komende activiteiten (spiergroepen die belast worden)
2. Herstel van gisteren/eergisteren (heupen na squats/runs, borst/schouder na push-heavy WOD, etc.)
3. Voorbereiding op morgen/overmorgen

Beschikbare mobiliteits-oefeningen:
{mobility_list}

OUTPUT FORMAT — stuur ALLEEN dit JSON-object, geen markdown, geen proza buiten het JSON:
{{
  "date": "<YYYY-MM-DD>",
  "coaching_note": "<1-2 zinnen in het Nederlands die de aanpassing uitleggen>",
  "intensity_level": "<licht|normaal|volledig>",
  "estimated_duration_min": <integer>,
  "exercises": [
    {{"id": "pushup_1", "name": "Pushups",  "sets": 1, "reps": <int>, "rest_s": 30, "adaptation_note": "<waarom aangepast, of lege string>"}},
    {{"id": "situp",    "name": "Sit-ups",  "sets": 1, "reps": <int>, "rest_s": 30, "adaptation_note": ""}},
    {{"id": "pushup_2", "name": "Pushups",  "sets": 1, "reps": <int>, "rest_s": 30, "adaptation_note": ""}},
    {{"id": "pushup_3", "name": "Pushups",  "sets": 1, "reps": <int>, "rest_s": 0,  "adaptation_note": ""}}
  ],
  "squat": {{
    "variant": "<variant_code uit schema>",
    "label": "<display naam>",
    "sub": "<bijv. KB 12kg, of lege string>",
    "sets": <int>,
    "reps": <int>,
    "note": "<optionele coaching tip, of lege string>"
  }},
  "mobility": [
    {{
      "id": "<id uit catalogus>",
      "name": "<naam uit catalogus>",
      "duration": "<duration uit catalogus>",
      "priority": <1 of 2>,
      "rationale": "<korte reden voor selectie>"
    }}
  ]
}}

Gebruik priority 2 voor de meest urgente/aanbevolen oefeningen (maximaal 3), priority 1 voor de rest.
"""


# ── Claude aanroepen ───────────────────────────────────────────────────────────

def _call_claude(context: str, squat: dict, target: date) -> dict | None:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system_prompt = _build_system_prompt(squat)
    dag_naam = DAY_NL[target.weekday()]

    user_message = (
        f"Genereer het thuistraining plan voor {dag_naam} {target.isoformat()}.\n\n"
        f"Hier is de volledige fitnesscontext:\n\n{context}"
    )

    log.info("Claude aanroepen voor thuistraining plan (model: %s)...", MODEL)
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    raw = response.content[0].text.strip()

    # Strip eventuele markdown code-fences
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Claude retourneerde geen geldig JSON: %s\nRaw output:\n%s", exc, raw[:500])
        return None


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    gist_id = os.environ.get("GIST_ID", "").strip()
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GIST_TOKEN") or "").strip()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if not gist_id:
        log.error("GIST_ID niet ingesteld"); return 1
    if not token:
        log.error("GITHUB_TOKEN niet ingesteld"); return 1
    if not api_key:
        log.error("ANTHROPIC_API_KEY niet ingesteld"); return 1

    target = _get_target_date()
    week = _get_program_week(target)
    squat = _get_squat_variant(week)
    log.info("Datum: %s | Programmaweek: %d | Squat: %s", target, week, squat["label"])

    files = load_gist(gist_id, token)
    data = _load_fitness_data(files)
    context = _build_context(data, target, week, squat)

    log.info("Context opgebouwd (%d tekens)", len(context))

    plan = _call_claude(context, squat, target)
    if not plan:
        return 1

    # Zorg dat datum en generated_at altijd correct zijn
    plan["date"] = target.isoformat()
    plan["generated_at"] = datetime.now(AMS).isoformat(timespec="seconds")

    patch_gist(gist_id, token, {GIST_FILENAME: json.dumps(plan, ensure_ascii=False, indent=2)})
    log.info("Plan opgeslagen als %s in Gist", GIST_FILENAME)

    notify.send_notification(
        "Thuistraining klaar 🏠",
        f"Je gepersonaliseerde plan voor vandaag is gereed — {plan.get('coaching_note', '')[:80]}",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
