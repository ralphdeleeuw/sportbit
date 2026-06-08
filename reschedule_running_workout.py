#!/usr/bin/env python3
"""
reschedule_running_workout.py — Verplaatst hardloopworkouts in intervals.icu
op basis van run_1/run_2 overrides in health_input.json.

Leest running_plan.json voor de bestaande event_id en workout_doc.
Verwijdert het oude intervals.icu event en maakt een nieuw aan op de nieuwe datum.
Ruimt daarna de overrides op in health_input.json.

GitHub Secrets vereist:
  INTERVALS_ATHLETE_ID, INTERVALS_API_KEY, GIST_ID, GITHUB_TOKEN
"""

from __future__ import annotations

import json
import logging
import os
import sys

import requests

from generate_running_workout import _build_intervals_event, _push_to_intervals
from gist_utils import load_gist as _load_gist, patch_gist as _patch_gist

log = logging.getLogger(__name__)
INTERVALS_BASE = "https://intervals.icu/api/v1/athlete"


def _gcal_reschedule(workout: dict, calendar_id: str, creds_json: str) -> None:
    """Verwijder oud Google Agenda event en maak nieuw aan op de verschoven datum."""
    try:
        from google_calendar_sync import GoogleCalendarSync
        cal = GoogleCalendarSync(creds_json=creds_json)
    except Exception as exc:
        log.error("Fout bij opzetten Google Agenda service: %s", exc)
        return

    old_gcal_id = workout.get("gcal_event_id")
    if old_gcal_id:
        try:
            cal.service.events().delete(calendarId=calendar_id, eventId=old_gcal_id).execute()
            log.info("Oud Google Agenda event %s verwijderd", old_gcal_id)
        except Exception as exc:
            log.warning("Kon oud Google Agenda event %s niet verwijderen: %s", old_gcal_id, exc)

    from datetime import datetime, timedelta
    time_str = workout.get("time", "20:00")
    if len(time_str) == 5:
        time_str += ":00"
    try:
        dt_start = datetime.fromisoformat(f"{workout['date']}T{time_str}")
    except (ValueError, KeyError):
        return

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

    body = {
        "summary":     f"🏃 {name}{dist_str}",
        "description": desc,
        "start": {"dateTime": dt_start.isoformat(), "timeZone": "Europe/Amsterdam"},
        "end":   {"dateTime": dt_end.isoformat(),   "timeZone": "Europe/Amsterdam"},
    }
    try:
        result = cal.create_event(calendar_id=calendar_id, event_details=body)
        workout["gcal_event_id"] = result.get("id")
        log.info("Nieuw Google Agenda event: '%s' op %s (%s)",
                 name, workout["date"], workout["gcal_event_id"])
    except Exception as exc:
        log.error("Fout bij aanmaken Google Agenda event: %s", exc)


def _cleanup_cancelled_workouts(
    workouts: list[dict],
    athlete_id: str,
    api_key: str,
    gcal_creds: str,
    gcal_cal_id: str,
) -> bool:
    """Verwijder intervals.icu en Google Agenda events voor geannuleerde workouts."""
    pending = [
        w for w in workouts
        if w.get("cancelled") and (w.get("event_id") or w.get("gcal_event_id"))
    ]
    if not pending:
        return False

    ints = requests.Session()
    ints.auth = ("API_KEY", api_key)
    ints.headers.update({"Accept": "application/json"})

    changed = False
    for workout in pending:
        name = workout.get("name") or workout.get("type") or "workout"
        log.info("Opruimen geannuleerde workout: %s op %s", name, workout.get("date", "?"))

        event_id = workout.get("event_id")
        if event_id:
            try:
                resp = ints.delete(
                    f"{INTERVALS_BASE}/{athlete_id}/events/{event_id}", timeout=20
                )
                if resp.ok:
                    log.info("intervals.icu event %s verwijderd", event_id)
                else:
                    log.warning(
                        "Kon intervals.icu event %s niet verwijderen: %s %s",
                        event_id, resp.status_code, resp.text[:200],
                    )
            except Exception as exc:
                log.warning("Fout bij verwijderen intervals.icu event %s: %s", event_id, exc)
            del workout["event_id"]
            changed = True

        gcal_id = workout.get("gcal_event_id")
        if gcal_id:
            if gcal_creds and gcal_cal_id:
                try:
                    from google_calendar_sync import GoogleCalendarSync
                    cal = GoogleCalendarSync(creds_json=gcal_creds)
                    cal.service.events().delete(
                        calendarId=gcal_cal_id, eventId=gcal_id
                    ).execute()
                    log.info("Google Agenda event %s verwijderd", gcal_id)
                except Exception as exc:
                    log.warning(
                        "Kon Google Agenda event %s niet verwijderen: %s", gcal_id, exc
                    )
            else:
                log.warning(
                    "Google Agenda credentials ontbreken — event %s niet verwijderd", gcal_id
                )
            del workout["gcal_event_id"]
            changed = True

    return changed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    athlete_id   = os.environ.get("INTERVALS_ATHLETE_ID", "").strip()
    api_key      = os.environ.get("INTERVALS_API_KEY", "").strip()
    gist_id      = os.environ.get("GIST_ID", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()

    missing = [n for n, v in [
        ("INTERVALS_ATHLETE_ID", athlete_id),
        ("INTERVALS_API_KEY", api_key),
        ("GIST_ID", gist_id),
        ("GITHUB_TOKEN", github_token),
    ] if not v]
    if missing:
        log.error("Vereiste environment variables ontbreken: %s", ", ".join(missing))
        sys.exit(1)

    gist_files = _load_gist(gist_id, github_token)

    try:
        health_input: dict = json.loads(gist_files.get("health_input.json") or "{}")
    except json.JSONDecodeError:
        health_input = {}

    try:
        plan: dict = json.loads(gist_files.get("running_plan.json") or "{}")
    except json.JSONDecodeError:
        plan = {}

    workouts: list[dict] = plan.get("workouts", [])
    changed = False

    overrides = {k: v for k, v in health_input.items() if k in ("run_1", "run_2")}
    if overrides:
        ints = requests.Session()
        ints.auth = ("API_KEY", api_key)
        ints.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

        for key, new_datetime in overrides.items():
            session_role = "speed" if key == "run_1" else "long_run"
            workout = next((w for w in workouts if w.get("session") == session_role), None)
            if not workout:
                log.warning("Geen %s workout in running_plan.json — overslaan", session_role)
                continue

            new_date = new_datetime[:10]
            new_time = new_datetime[11:16] if len(new_datetime) >= 16 else (
                "19:00" if key == "run_1" else "07:15"
            )

            log.info(
                "Verplaatsen %s (%s): %s → %s %s",
                key, session_role, workout.get("date"), new_date, new_time,
            )

            # Verwijder oud intervals.icu event
            old_id = workout.get("event_id")
            if old_id:
                try:
                    resp = ints.delete(
                        f"{INTERVALS_BASE}/{athlete_id}/events/{old_id}", timeout=20
                    )
                    if resp.ok:
                        log.info("Oud event %s verwijderd", old_id)
                    else:
                        log.warning(
                            "Kon event %s niet verwijderen: %s %s",
                            old_id, resp.status_code, resp.text[:200],
                        )
                except Exception as exc:
                    log.warning("Fout bij verwijderen event %s: %s", old_id, exc)
            else:
                log.info("Geen event_id voor %s — oud event niet verwijderd", key)

            # Maak nieuw event aan op de nieuwe datum.
            # Gebruik _build_intervals_event zodat de ICU-description (voor server-side
            # parsing naar workout_doc.steps) én de workout_doc altijd correct zijn.
            rescheduled_spec = {**workout, "date": new_date, "time": new_time}
            new_event = _build_intervals_event(rescheduled_spec)

            results = _push_to_intervals(athlete_id, api_key, [new_event])
            result = results[0] if results else None
            if not result:
                log.error("Kon nieuw intervals.icu event niet aanmaken voor %s", key)
                continue

            new_id = result.get("id")
            log.info("Nieuw intervals.icu event: id=%s op %s %s", new_id, new_date, new_time)
            workout["date"] = new_date
            workout["time"] = new_time
            workout["event_id"] = new_id
            del health_input[key]
            changed = True

            # Google Agenda sync
            gcal_creds_json  = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
            gcal_calendar_id = os.environ.get("CALENDAR_ID", "").strip()
            if gcal_creds_json and gcal_calendar_id:
                _gcal_reschedule(workout, gcal_calendar_id, gcal_creds_json)
    else:
        log.info("Geen verplaatsingen in health_input.json")

    # Verwijder calendar events voor geannuleerde workouts
    gcal_creds_json  = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
    gcal_calendar_id = os.environ.get("CALENDAR_ID", "").strip()
    if _cleanup_cancelled_workouts(workouts, athlete_id, api_key, gcal_creds_json, gcal_calendar_id):
        changed = True

    if changed:
        _patch_gist(gist_id, github_token, {
            "health_input.json": json.dumps(health_input, indent=2, ensure_ascii=False),
            "running_plan.json": json.dumps(plan, indent=2, ensure_ascii=False),
        })
        log.info("Gist bijgewerkt")

    log.info("Klaar.")


if __name__ == "__main__":
    main()
