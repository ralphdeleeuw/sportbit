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
  PUSHOVER_USER_KEY     — (optioneel) Pushover user key
  PUSHOVER_API_TOKEN    — (optioneel) Pushover API token

Eenmalige instelling:
  intervals.icu → Settings → Connected Accounts → Garmin
  → "Sync planned workouts to Garmin" inschakelen
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import anthropic
import requests

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
    "crossfit_schedule": "Maandag 20:00, Woensdag 08:00, Donderdag 20:00, Zaterdag 09:00, Zondag 09:00",
    "run_sessions": [
        {"day": "Tuesday",  "time": "20:00", "role": "speed"},
        {"day": "Saturday", "time": "09:00", "role": "long_run"},
    ],
    "schedule_note": "Hardloopdagen zijn standaard dinsdag en zaterdag, maar kunnen via health_input.json worden verplaatst.",
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

def _load_fitness_context(gist_id: str, token: str) -> dict:
    files = _load_gist(gist_id, token)

    wod_raw = files.get("sugarwod_wod.json", "")
    wod_data = _parse_json(wod_raw, "sugarwod_wod.json") or {}

    health_raw = files.get("health_input.json", "")
    health_input = _parse_json(health_raw, "health_input.json")

    plan_raw = files.get("running_plan.json", "")
    running_plan = _parse_json(plan_raw, "running_plan.json") or {}

    intervals_data = wod_data.get("intervals_data") or {}

    return {
        "wellness": intervals_data.get("wellness", {}).get("by_date", {}),
        "activities": intervals_data.get("activities", {}).get("by_date", {}),
        "health_input": health_input or {},
        "running_plan": running_plan,
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
        if w.get("hrv"):       parts.append(f"HRV={w['hrv']}ms")
        if w.get("resting_hr"):parts.append(f"rustpols={w['resting_hr']}bpm")
        if w.get("sleep_hrs"): parts.append(f"slaap={w['sleep_hrs']}u")
        if w.get("ctl") is not None: parts.append(f"CTL={w['ctl']}")
        if w.get("atl") is not None: parts.append(f"ATL={w['atl']}")
        if w.get("tsb") is not None: parts.append(f"TSB={w['tsb']}")
        wellness_lines.append(" ".join(parts))

    activities_by_date: dict = ctx["activities"]
    run_lines = []
    for d in sorted(activities_by_date.keys(), reverse=True)[:21]:
        for act in activities_by_date.get(d, []):
            act_type = (act.get("type") or "").lower()
            if not any(rt in act_type for rt in ["run", "running", "jog"]):
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
                parts.append(f"gem.HR {act['avg_hr']}bpm")
            run_lines.append(" ".join(parts))

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
        f"Datum vandaag: {today.isoformat()}",
        f"Weeknummer in continu 5K-programma: week {week_number}",
        f"Sessie 1 — snelheidswerk: {run1_date.isoformat()} om {run1_time} (gebruik deze datum en tijd exact)",
        f"Sessie 2 — lange duurloop: {run2_date.isoformat()} om {run2_time} (gebruik deze datum en tijd exact)",
        f"Huidig 5K-tempo: {ATHLETE_PROFILE['current_5k_pace']}/km ({ATHLETE_PROFILE['current_5k_min']} min)",
        f"Doel 5K-tempo: {ATHLETE_PROFILE['target_5k_pace']}/km ({ATHLETE_PROFILE['target_5k_min']} min)",
    ]

    if wellness_lines:
        sections.append("Hersteldata (laatste 7 dagen):\n" + "\n".join(wellness_lines))
    else:
        sections.append("Hersteldata: niet beschikbaar")

    if run_lines:
        sections.append("Recente hardloopactiviteiten:\n" + "\n".join(run_lines[:8]))
    else:
        sections.append("Recente hardloopactiviteiten: geen — dit is de start van het programma")

    if health_lines:
        sections.append("Subjectieve gezondheidsscores:\n" + "\n".join(health_lines))

    return "\n\n".join(sections)


# ── Claude prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Je bent een professionele hardloopcoach. Je maakt werkschema's voor Ralph de Leeuw:
- 47 jaar, 77kg, CrossFit 5x/week, hardloopt 2x/week
- Huidig 5K: ~28 min (5:36/km) | Doel: 26 min (5:12/min)
- Standaard: dinsdag 20:00 = snelheidswerk | zaterdag 09:00 = lange duurloop
- De exacte data en tijden worden in de context meegegeven — gebruik die altijd exact

Pacezones (stem altijd af op herstelstatus via HRV/TSB):
- Conversational (max):  6:40/km — "geen sneller dan 6:40/km"
- Aeroob:                6:00-6:20/km
- Drempel:               5:45-5:55/km
- 5K race tempo (nu):    5:30-5:42/km
- Intervaltempo 800m:    5:20-5:30/km
- Intervaltempo 400m:    5:10-5:25/km
- Intervaltempo 300m:    5:20-5:35/km
- Intervaltempo 200m:    5:00-5:15/km

Periodi­sering (continu, geen einddatum):
- Week 1-4:   basis opbouwen — easy duurlopen + lichte fartlek, max 6km zaterdag
- Week 5-8:   eerste structuurwerk — rolling repeats (300m/400m), progressive long runs
- Week 9-12:  intensiteit — Fast 8-4-2s stijl, drempelintervallen, langere long runs
- Week 13+:   consolidatie + race prep — elke 4e week herstelweek (30% minder volume)
- Lage HRV (<35ms) of negatieve TSB (<-15): kies altijd de lichtere variant

Werkwoord: geef ALLEEN geldige JSON terug (geen markdown, geen uitleg):
[
  {
    "date": "YYYY-MM-DD",
    "session": "speed|long_run",
    "type": "easy_run|fartlek|interval_run|progressive_run|tempo_run",
    "name": "Korte Nederlandse sessienaam (zoals Runna: 'Rolling 300s', 'Progressive duurloop')",
    "description": "1-2 zinnen over het doel van deze sessie",
    "total_distance_km": <float>,
    "steps": [
      <stappen — zie formaat hieronder>
    ]
  }
]

Stap­formaten:
  Warming-up:   {"type":"warmup",   "distance_m":<int>, "pace_max":"M:SS"}
  Rustige run:  {"type":"run",      "distance_m":<int>, "pace_target":"M:SS"} of {"duration_min":<int>, "pace_max":"M:SS"}
  Herhaling:    {"type":"repeat",   "count":<int>, "children":[<stappen>]}
  Walking rest: {"type":"rest",     "duration_s":<int>}
  Cooling-down: {"type":"cooldown", "distance_m":<int>, "pace_max":"M:SS"}

Pace: schrijf als "M:SS" (bijv. "6:40", "5:35"). Gebruik altijd distance_m voor intervallen, duration_min voor easy stukken.
Walking rest na het hele herhaling­blok (niet per herhaling) als het een lange pauze is.
Zaterdag-sessie: altijd progressive_run of easy_run, 5-9km afhankelijk van weeknummer."""


def _generate_plan_claude(context_text: str) -> list[dict]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": "Genereer het hardloopschema voor aankomende week:\n\n" + context_text,
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
    """Converteer een Claude-stap naar intervals.icu workout_doc stap.

    Warmup/cooldown: tijd in seconden (afstand → berekend via pace).
    Run/intervalstap: afstand in meters als distance_m aanwezig is,
    anders tijd in seconden. Garmin toont dan "Xm remaining" i.p.v. afteltimer.
    """
    stype = step.get("type")

    def to_secs(s: dict) -> int | None:
        if s.get("duration_s"):
            return int(s["duration_s"])
        if s.get("duration_min"):
            return int(s["duration_min"] * 60)
        if s.get("distance_m"):
            pace_str = s.get("pace_target") or s.get("pace_max")
            pace_sec = _pace_to_sec_per_km(pace_str) if pace_str else 400
            return int(s["distance_m"] / 1000 * pace_sec)
        return None

    def pace_target(s: dict) -> dict | None:
        if s.get("pace_target"):
            sec = _pace_to_sec_per_km(s["pace_target"])
            return {"type": "pace", "pace": sec, "paceRange": 10}
        if s.get("pace_max"):
            sec = _pace_to_sec_per_km(s["pace_max"])
            return {"type": "pace", "pace": sec, "paceRange": 30}
        return None

    if stype in ("warmup", "cooldown"):
        # Warmup/cooldown: altijd tijd — geen harde afstandsdoelen
        dur = to_secs(step)
        if not dur:
            return None
        doc: dict = {"type": stype, "duration": dur}
        t = pace_target(step)
        if t:
            doc["target"] = t
        return doc

    if stype == "run":
        # Interval/run stap: gebruik afstand als die bekend is (Fenix toont "Xm remaining")
        if step.get("distance_m"):
            doc = {"type": "active", "duration": step["distance_m"], "durationType": "Distance"}
        else:
            dur = to_secs(step)
            if not dur:
                return None
            doc = {"type": "active", "duration": dur}
        t = pace_target(step)
        if t:
            doc["target"] = t
        return doc

    if stype == "rest":
        dur = to_secs(step)
        return {"type": "rest", "duration": dur} if dur else None

    if stype == "repeat":
        children = [_step_to_doc(c) for c in step.get("children", [])]
        return {
            "type": "Repeat",
            "reps": step["count"],
            "steps": [c for c in children if c],
        }

    return None


def _build_workout_doc(spec: dict) -> dict | None:
    steps = [_step_to_doc(s) for s in spec.get("steps", [])]
    steps = [s for s in steps if s]
    return {"steps": steps} if steps else None


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
            pace_str = f" (geen sneller dan {pace}/km)" if pace else ""
            lines.append(f"{dist_str}warming-up in conversational pace{pace_str}")

        elif stype == "cooldown":
            dist = step.get("distance_m", "")
            dist_str = f"{dist/1000:.1f}km " if dist else ""
            lines.append(f"\n{dist_str}cooling-down in conversational pace (of langzamer!)")

        elif stype == "run":
            dist = step.get("distance_m")
            dur = step.get("duration_min")
            pace = step.get("pace_target") or step.get("pace_max")
            if dist:
                pace_str = f" op {pace}/km" if pace else ""
                lines.append(f"{dist}m{pace_str}")
            elif dur:
                pace_str = f" (max {pace}/km)" if pace else ""
                lines.append(f"{dur} min{pace_str}")

        elif stype == "repeat":
            count = step.get("count", "?")
            lines.append(f"\nHerhaal het volgende {count}x:")
            lines.append("----------")
            for child in step.get("children", []):
                ct = child.get("type")
                if ct == "run":
                    dist = child.get("distance_m")
                    pace = child.get("pace_target") or child.get("pace_max")
                    pace_str = f" op {pace}/km" if pace else ""
                    lines.append(f"{dist}m{pace_str}" if dist else "run")
                elif ct == "rest":
                    dur_s = child.get("duration_s", 0)
                    lines.append(f"{dur_s}s wandel-herstel")
            lines.append("----------")

        elif stype == "rest":
            dur_s = step.get("duration_s", 0)
            lines.append(f"\n{dur_s}s wandel-herstel")

    week = spec.get("week_number", "")
    if week:
        lines.append(f"\n5K Verbeteringsprogramma (Week {week})")

    return "\n".join(lines)


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

    description = _build_description(spec)
    workout_doc = _build_workout_doc(spec)

    event: dict = {
        "start_date_local": f"{spec['date']}T{time_str}",
        "category": "WORKOUT",
        "type": "Run",
        "name": spec["name"],
        "description": description,
    }
    if workout_doc:
        event["workout_doc"] = workout_doc

    return event


# ── Push naar intervals.icu ────────────────────────────────────────────────────

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
            log.info(
                "Event aangemaakt: '%s' op %s om %s (id: %s)",
                event["name"],
                event["start_date_local"][:10],
                event["start_date_local"][11:16],
                result.get("id"),
            )
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


# ── Pushover notificatie ───────────────────────────────────────────────────────

def _notify_pushover(specs: list[dict]) -> None:
    user_key = os.environ.get("PUSHOVER_USER_KEY", "")
    api_token = os.environ.get("PUSHOVER_API_TOKEN", "")
    if not user_key or not api_token:
        return

    lines = ["Hardloopschema deze week:"]
    for s in specs:
        d = datetime.strptime(s["date"], "%Y-%m-%d")
        dag = ["ma", "di", "wo", "do", "vr", "za", "zo"][d.weekday()]
        time_str = s.get("time", "20:00" if s.get("session") == "speed" else "09:00")
        dist = s.get("total_distance_km", "?")
        lines.append(f"\n{dag} {d.day}/{d.month} {time_str} — {s['name']} ({dist}km)")

    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": api_token, "user": user_key,
                  "title": "Hardloopplan klaar", "message": "\n".join(lines)},
            timeout=10,
        )
        log.info("Pushover notificatie verstuurd")
    except Exception as exc:
        log.warning("Pushover mislukt: %s", exc)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    athlete_id   = os.environ.get("INTERVALS_ATHLETE_ID", "").strip()
    api_key      = os.environ.get("INTERVALS_API_KEY", "").strip()
    gist_id      = os.environ.get("GIST_ID", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()

    missing = [name for name, val in [
        ("INTERVALS_ATHLETE_ID", athlete_id),
        ("INTERVALS_API_KEY", api_key),
        ("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")),
        ("GIST_ID", gist_id),
        ("GITHUB_TOKEN", github_token),
    ] if not val]
    if missing:
        log.error("Vereiste environment variables ontbreken: %s", ", ".join(missing))
        sys.exit(1)

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

    _notify_pushover(specs)

    log.info("Klaar! %d workout(s) gepland in intervals.icu.", len(specs))


if __name__ == "__main__":
    main()
