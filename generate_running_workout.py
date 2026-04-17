#!/usr/bin/env python3
"""
generate_running_workout.py — Genereert een gepersonaliseerd hardloopschema via Claude
en pusht dit naar intervals.icu (dat automatisch synchroniseert naar Garmin Connect → Fenix).

Workflow:
1. Laad fitnessdata uit GitHub Gist (wellness, activiteiten, herstelscores)
2. Genereer 2 hardloopsessies via Claude API (afgestemd op 5K doel + herstelstatus)
3. Push workouts als events naar intervals.icu API
4. Sla plan op in Gist als running_plan.json
5. Stuur Pushover-notificatie

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
  Daarna verschijnen workouts automatisch op de Garmin Fenix.
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
    "goal": "5K race (sneller worden)",
    "running_base": "enige basis — kan 5-10km lopen maar niet regelmatig geweest",
    "runs_per_week": 2,
    "crossfit_days": ["Maandag", "Woensdag", "Donderdag", "Zaterdag", "Zondag"],
    "run_days": ["Dinsdag", "Vrijdag"],
}

# HR zones (geschat max HR 173bpm op leeftijd 47)
HR_ZONES = {
    1: (0, 104),
    2: (104, 121),
    3: (121, 138),
    4: (138, 156),
    5: (156, 173),
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

def _build_claude_context(ctx: dict) -> str:
    today = date.today()

    # Wellness laatste 7 dagen
    wellness_by_date: dict = ctx["wellness"]
    recent_dates = sorted(wellness_by_date.keys(), reverse=True)[:7]
    wellness_lines = []
    for d in recent_dates:
        w = wellness_by_date[d]
        parts = [f"  {d}:"]
        if w.get("hrv"):
            parts.append(f"HRV={w['hrv']}ms")
        if w.get("resting_hr"):
            parts.append(f"rustpols={w['resting_hr']}bpm")
        if w.get("sleep_hrs"):
            parts.append(f"slaap={w['sleep_hrs']}u")
        if w.get("sleep_score"):
            parts.append(f"slaapscore={w['sleep_score']}/100")
        if w.get("ctl") is not None:
            parts.append(f"CTL={w['ctl']}")
        if w.get("atl") is not None:
            parts.append(f"ATL={w['atl']}")
        if w.get("tsb") is not None:
            parts.append(f"TSB={w['tsb']}")
        wellness_lines.append(" ".join(parts))

    # Recente hardloopactiviteiten (laatste 21 dagen)
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
            if act.get("training_load"):
                parts.append(f"load={act['training_load']}")
            run_lines.append(" ".join(parts))

    # Week nummer
    running_plan = ctx["running_plan"]
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

    # Bepaal hardloopdagen aankomende week
    tuesday = today + timedelta(days=(1 - today.weekday()) % 7)
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    if tuesday <= today:
        tuesday += timedelta(weeks=1)
    if friday <= today:
        friday += timedelta(weeks=1)

    # Subjectieve gezondheidsscores
    health_input = ctx.get("health_input") or {}
    health_lines = []
    for k, v in health_input.items():
        if k != "date":
            health_lines.append(f"  - {k}: {v}")

    sections = [
        f"Datum vandaag: {today.isoformat()}",
        f"Aankomende hardloopdagen: dinsdag {tuesday.isoformat()}, vrijdag {friday.isoformat()}",
        f"Weeknummer in 5K programma: week {week_number}",
    ]

    if wellness_lines:
        sections.append("Hersteldata (laatste 7 dagen):\n" + "\n".join(wellness_lines))
    else:
        sections.append("Hersteldata: niet beschikbaar")

    if run_lines:
        sections.append("Recente hardloopactiviteiten:\n" + "\n".join(run_lines[:8]))
    else:
        sections.append("Recente hardloopactiviteiten: geen gevonden (begin van het programma)")

    if health_lines:
        sections.append("Subjectieve gezondheidsscores:\n" + "\n".join(health_lines))

    return "\n\n".join(sections)


# ── Claude plan genereren ──────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Je bent een professionele hardloopcoach. Je maakt gepersonaliseerde 5K-trainingssessies voor Ralph de Leeuw:
- 47 jaar, 77kg, CrossFit 5x/week (ma/wo/do/za/zo), hardlopen 2x/week (di/vrij)
- Doel: 5K race — snelheidsopbouw over meerdere weken
- Basis: kan 5-10km lopen maar niet regelmatig geweest

Hartslag zones (max HR ~173bpm):
- Zone 2: 104-121bpm (aerobe basis, makkelijk gesprek mogelijk)
- Zone 3: 121-138bpm (comfortabel uitdagend)
- Zone 4: 138-156bpm (drempelintensiteit, hard)
- Zone 5: 156+bpm (maximaal)

Periodiseringsrichtlijnen:
- Week 1-3: opbouw basis (beide sessies easy, zone 2, 20-35min)
- Week 4-6: eerste snelheidswerk (1 easy + 1 fartlek of tempo 20min)
- Week 7+: structurele intervallen (1 easy/tempo + 1 interval 4-6x400m of 3x800m)
- Pas aan op basis van herstelstatus: lage HRV of hoge ATL → minder intensiteit

Geef ALLEEN geldig JSON terug (geen markdown, geen uitleg erbuiten):
[
  {
    "date": "YYYY-MM-DD",
    "type": "easy_run|tempo_run|interval_run",
    "name": "Korte Nederlandse naam",
    "description": "Beschrijving van doel en uitvoering (2-3 zinnen)",
    "total_duration_min": <int>,
    "steps": [
      {"type": "warmup", "duration_min": <int>},
      {"type": "run", "duration_min": <int>, "hr_zone": <1-5>},
      {"type": "cooldown", "duration_min": <int>}
    ]
  }
]

Voor interval_run gebruik:
  {"type": "repeat", "count": <int>, "children": [
    {"type": "run", "distance_m": <int>, "hr_zone": <4-5>},
    {"type": "rest", "duration_min": <int>}
  ]}
"""


def _generate_plan_claude(context_text: str) -> list[dict]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                "Genereer het hardloopschema voor aankomende week op basis van "
                "deze fitnessdata:\n\n" + context_text
            ),
        }],
    )

    raw = message.content[0].text.strip()
    # Strip markdown code fences als aanwezig
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:].lstrip()

    return json.loads(raw)


# ── Intervals.icu event bouwen ─────────────────────────────────────────────────

def _build_description(spec: dict) -> str:
    lines = []
    desc = spec.get("description", "")
    if desc:
        lines.append(desc)
        lines.append("")

    lines.append("Workout:")
    for step in spec.get("steps", []):
        stype = step.get("type")
        if stype == "warmup":
            lines.append(f"  • Warming-up: {step.get('duration_min', '?')} min (rustig inlopen)")
        elif stype == "cooldown":
            lines.append(f"  • Cooling-down: {step.get('duration_min', '?')} min (rustig uitlopen)")
        elif stype == "run":
            zone = step.get("hr_zone")
            hr = HR_ZONES.get(zone, (0, 0))
            dur = step.get("duration_min")
            dist = step.get("distance_m")
            if dist:
                lines.append(f"  • Lopen: {dist}m — HR zone {zone} ({hr[0]}-{hr[1]} bpm)")
            elif dur:
                lines.append(f"  • Lopen: {dur} min — HR zone {zone} ({hr[0]}-{hr[1]} bpm)")
        elif stype == "repeat":
            lines.append(f"  • {step['count']}x herhalen:")
            for child in step.get("children", []):
                ct = child.get("type")
                if ct == "run":
                    dist = child.get("distance_m")
                    zone = child.get("hr_zone")
                    hr = HR_ZONES.get(zone, (0, 0))
                    lines.append(f"      – Snel: {dist}m — HR zone {zone} ({hr[0]}-{hr[1]} bpm)")
                elif ct == "rest":
                    lines.append(f"      – Herstel: {child.get('duration_min', '?')} min (wandelen)")
        elif stype == "rest":
            lines.append(f"  • Herstel: {step.get('duration_min', '?')} min")

    return "\n".join(lines)


def _build_intervals_event(spec: dict) -> dict:
    event: dict = {
        "start_date_local": f"{spec['date']}T08:00:00",
        "category": "WORKOUT",
        "name": spec["name"],
        "description": _build_description(spec),
    }
    return event


# ── Push naar intervals.icu ────────────────────────────────────────────────────

def _push_to_intervals(athlete_id: str, api_key: str, events: list[dict]) -> list[dict]:
    session = requests.Session()
    session.auth = ("API_KEY", api_key)
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    created = []
    for event in events:
        url = f"{INTERVALS_BASE}/{athlete_id}/events"
        log.info("Payload naar intervals.icu: %s", json.dumps(event, ensure_ascii=False))
        try:
            resp = session.post(url, json=event, timeout=20)
            if not resp.ok:
                log.error(
                    "Fout bij aanmaken event '%s': %s — response: %s",
                    event.get("name"), resp.status_code, resp.text[:500],
                )
                continue
            result = resp.json()
            log.info(
                "Event aangemaakt: '%s' op %s (id: %s)",
                event["name"],
                event["start_date_local"][:10],
                result.get("id"),
            )
            created.append(result)
        except Exception as exc:
            log.error("Fout bij aanmaken event '%s': %s", event.get("name"), exc)

    return created


# ── Sla plan op in Gist ────────────────────────────────────────────────────────

def _save_plan_to_gist(gist_id: str, token: str, specs: list[dict], week_number: int) -> None:
    plan_start = specs[0]["date"] if specs else date.today().isoformat()
    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week_number": week_number,
        "plan_start_date": plan_start,
        "workouts": specs,
    }
    _save_to_gist(gist_id, token, "running_plan.json", json.dumps(plan, indent=2, ensure_ascii=False))
    log.info("running_plan.json opgeslagen in Gist (week %d)", week_number)


# ── Pushover notificatie ───────────────────────────────────────────────────────

def _notify_pushover(specs: list[dict]) -> None:
    user_key = os.environ.get("PUSHOVER_USER_KEY", "")
    api_token = os.environ.get("PUSHOVER_API_TOKEN", "")
    if not user_key or not api_token:
        log.info("Pushover niet ingesteld — notificatie overgeslagen")
        return

    lines = ["Hardloopschema deze week:"]
    for s in specs:
        dur = s.get("total_duration_min", "?")
        wtype = s.get("type", "").replace("_", " ")
        lines.append(f"\n{s['date']} - {s['name']}")
        lines.append(f"{dur} min | {wtype}")

    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": api_token,
                "user": user_key,
                "title": "Hardloopplan klaar",
                "message": "\n".join(lines),
            },
            timeout=10,
        )
        log.info("Pushover notificatie verstuurd")
    except Exception as exc:
        log.warning("Pushover mislukt: %s", exc)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    athlete_id = os.environ.get("INTERVALS_ATHLETE_ID", "").strip()
    api_key = os.environ.get("INTERVALS_API_KEY", "").strip()
    gist_id = os.environ.get("GIST_ID", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()

    missing = [
        name for name, val in [
            ("INTERVALS_ATHLETE_ID", athlete_id),
            ("INTERVALS_API_KEY", api_key),
            ("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")),
            ("GIST_ID", gist_id),
            ("GITHUB_TOKEN", github_token),
        ] if not val
    ]
    if missing:
        log.error("Vereiste environment variables ontbreken: %s", ", ".join(missing))
        sys.exit(1)

    # 1. Laad fitnessdata
    log.info("Laden fitnessdata uit Gist...")
    ctx = _load_fitness_context(gist_id, github_token)

    # 2. Bouw context voor Claude
    context_text = _build_claude_context(ctx)
    log.info("Context klaar:\n%s", context_text)

    # 3. Genereer plan via Claude
    log.info("Hardloopplan genereren via Claude...")
    specs = _generate_plan_claude(context_text)
    log.info("Claude genereerde %d workout(s)", len(specs))
    for s in specs:
        log.info("  - %s: %s (%s min, %s)", s["date"], s["name"], s.get("total_duration_min", "?"), s.get("type"))

    # 4. Bouw intervals.icu events
    events = [_build_intervals_event(s) for s in specs]

    # 5. Push naar intervals.icu
    log.info("Workouts pushen naar intervals.icu...")
    _push_to_intervals(athlete_id, api_key, events)

    # 6. Bepaal weeknummer
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

    # 7. Sla plan op
    _save_plan_to_gist(gist_id, github_token, specs, week_number)

    # 8. Notificatie
    _notify_pushover(specs)

    log.info("Klaar! %d workout(s) gepland in intervals.icu.", len(specs))


if __name__ == "__main__":
    main()
