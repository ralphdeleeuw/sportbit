#!/usr/bin/env python3
"""
sync_to_gcal.py — Synchroniseert hardloopworkouts en persoonlijke events naar Google Agenda.

Verwerkt:
  1. running_plan.json  — workouts zonder gcal_event_id en niet geannuleerd
  2. personal_events.json — persoonlijke events zonder gcal_event_id

Slaat de nieuwe gcal_event_ids terug op in de Gist.

GitHub Secrets vereist:
  GIST_ID, GITHUB_TOKEN, GOOGLE_CREDENTIALS, CALENDAR_ID
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta

import requests

from gist_utils import load_gist as _load_gist, patch_gist as _patch_gist

log = logging.getLogger(__name__)

_TITLE_EMOJI: dict[str, str] = {
    "mountainbiken": "🚵",
    "fietsen": "🚴",
    "hiken": "🥾",
    "wandelen": "🚶",
    "zwemmen": "🏊",
    "suppen": "🏄",
    "yoga": "🧘",
    "gym": "🏋️",
    "crossfit": "🏋️",
    "hardlopen": "🏃",
}


def _emoji_for_title(title: str) -> str:
    t = title.lower()
    for key, emoji in _TITLE_EMOJI.items():
        if key in t:
            return emoji
    return "📅"


def _personal_event_gcal_body(event: dict) -> dict:
    title = event.get("title", "Event")
    emoji = _emoji_for_title(title)
    date = event.get("date", "")
    time_str = event.get("time", "")

    desc_parts = []
    if event.get("route"):
        desc_parts.append(f"Route: {event['route']}")
    if event.get("notes"):
        desc_parts.append(event["notes"])

    body: dict = {
        "summary": f"{emoji} {title}" + (f" — {event['notes']}" if event.get("notes") else ""),
        "description": "\n".join(desc_parts),
    }
    if event.get("location"):
        body["location"] = event["location"]

    if time_str:
        time_full = time_str + ":00" if len(time_str) == 5 else time_str
        try:
            dt_start = datetime.fromisoformat(f"{date}T{time_full}")
            dt_end = dt_start + timedelta(hours=2)
            body["start"] = {"dateTime": dt_start.isoformat(), "timeZone": "Europe/Amsterdam"}
            body["end"]   = {"dateTime": dt_end.isoformat(),   "timeZone": "Europe/Amsterdam"}
        except ValueError:
            body["start"] = {"date": date}
            body["end"]   = {"date": date}
    else:
        body["start"] = {"date": date}
        body["end"]   = {"date": date}

    return body


def _run_event_gcal_body(workout: dict) -> dict | None:
    time_str = workout.get("time", "20:00" if workout.get("session") == "speed" else "09:00")
    if len(time_str) == 5:
        time_str += ":00"
    try:
        dt_start = datetime.fromisoformat(f"{workout['date']}T{time_str}")
    except (ValueError, KeyError):
        return None

    dist_km = workout.get("total_distance_km")
    dur_min  = workout.get("total_duration_min")
    if dur_min:
        dt_end = dt_start + timedelta(minutes=dur_min)
    elif dist_km:
        dt_end = dt_start + timedelta(minutes=round(float(dist_km) * 6.5))
    else:
        dt_end = dt_start + timedelta(hours=1)

    name     = workout.get("name") or workout.get("type") or "Hardloopworkout"
    dist_str = f" ({dist_km}km)" if dist_km else ""
    desc     = workout.get("description") or ""
    week_nr  = workout.get("week_number")
    if week_nr:
        desc = f"5K-programma week {week_nr}\n\n" + desc

    return {
        "summary":     f"🏃 {name}{dist_str}",
        "description": desc,
        "start": {"dateTime": dt_start.isoformat(), "timeZone": "Europe/Amsterdam"},
        "end":   {"dateTime": dt_end.isoformat(),   "timeZone": "Europe/Amsterdam"},
    }


def sync_running_workouts(
    plan: dict, cal: object, cal_id: str
) -> bool:
    today = datetime.today().strftime("%Y-%m-%d")
    pending = [
        w for w in plan.get("workouts", [])
        if not w.get("cancelled") and not w.get("gcal_event_id") and w.get("date", "") >= today
    ]
    if not pending:
        log.info("Geen hardloopworkouts zonder Google Agenda event")
        return False

    changed = False
    for workout in pending:
        body = _run_event_gcal_body(workout)
        if not body:
            continue
        try:
            result = cal.create_event(calendar_id=cal_id, event_details=body)
            workout["gcal_event_id"] = result.get("id")
            log.info(
                "Hardloopworkout aangemaakt: '%s' op %s (%s)",
                workout.get("name"), workout["date"], workout["gcal_event_id"],
            )
            changed = True
        except Exception as exc:
            log.error("Fout bij aanmaken run event voor %s: %s", workout.get("date"), exc)

    return changed


def sync_personal_events(
    personal_data: dict, cal: object, cal_id: str
) -> bool:
    today = datetime.today().strftime("%Y-%m-%d")
    events = personal_data.get("events", [])
    pending = [
        e for e in events
        if not e.get("gcal_event_id") and e.get("date", "") >= today
    ]
    if not pending:
        log.info("Geen persoonlijke events zonder Google Agenda event")
        return False

    changed = False
    for event in pending:
        body = _personal_event_gcal_body(event)
        try:
            result = cal.create_event(calendar_id=cal_id, event_details=body)
            event["gcal_event_id"] = result.get("id")
            log.info(
                "Persoonlijk event aangemaakt: '%s' op %s (%s)",
                event.get("title"), event["date"], event["gcal_event_id"],
            )
            changed = True
        except Exception as exc:
            log.error(
                "Fout bij aanmaken persoonlijk event '%s' (%s): %s",
                event.get("title"), event.get("date"), exc,
            )

    return changed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    gist_id      = os.environ.get("GIST_ID", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    gcal_creds   = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
    gcal_cal_id  = os.environ.get("CALENDAR_ID", "").strip()

    missing = [n for n, v in [
        ("GIST_ID", gist_id),
        ("GITHUB_TOKEN", github_token),
        ("GOOGLE_CREDENTIALS", gcal_creds),
        ("CALENDAR_ID", gcal_cal_id),
    ] if not v]
    if missing:
        log.error("Vereiste environment variables ontbreken: %s", ", ".join(missing))
        sys.exit(1)

    try:
        from google_calendar_sync import GoogleCalendarSync
        cal = GoogleCalendarSync(creds_json=gcal_creds)
    except Exception as exc:
        log.error("Fout bij opzetten Google Agenda service: %s", exc)
        sys.exit(1)

    gist_files = _load_gist(gist_id, github_token)

    try:
        plan: dict = json.loads(gist_files.get("running_plan.json") or "{}")
    except json.JSONDecodeError:
        plan = {}

    try:
        personal_data: dict = json.loads(gist_files.get("personal_events.json") or "{}")
    except json.JSONDecodeError:
        personal_data = {}

    changed_plan     = sync_running_workouts(plan, cal, gcal_cal_id)
    changed_personal = sync_personal_events(personal_data, cal, gcal_cal_id)

    files_to_patch: dict[str, str] = {}
    if changed_plan:
        files_to_patch["running_plan.json"] = json.dumps(plan, indent=2, ensure_ascii=False)
    if changed_personal:
        files_to_patch["personal_events.json"] = json.dumps(
            personal_data, indent=2, ensure_ascii=False
        )

    if files_to_patch:
        _patch_gist(gist_id, github_token, files_to_patch)
        log.info("Gist bijgewerkt met nieuwe gcal_event_ids")
    else:
        log.info("Niets gewijzigd — alles al gesynchroniseerd")

    log.info("Klaar.")


if __name__ == "__main__":
    main()
