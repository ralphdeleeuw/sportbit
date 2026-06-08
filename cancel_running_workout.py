#!/usr/bin/env python3
"""
cancel_running_workout.py — Verwijdert Google Agenda en intervals.icu events
voor geannuleerde hardloopworkouts.

Leest running_plan.json uit de Gist, vindt workouts met cancelled=true die
nog een gcal_event_id of event_id hebben, verwijdert die events en ruimt
de IDs op in de Gist.

GitHub Secrets vereist:
  INTERVALS_ATHLETE_ID, INTERVALS_API_KEY, GIST_ID, GITHUB_TOKEN
Optioneel:
  GOOGLE_CREDENTIALS, CALENDAR_ID
"""

from __future__ import annotations

import json
import logging
import os
import sys

import requests

from gist_utils import load_gist as _load_gist, patch_gist as _patch_gist

log = logging.getLogger(__name__)
INTERVALS_BASE = "https://intervals.icu/api/v1/athlete"


def _delete_gcal_event(gcal_event_id: str, calendar_id: str, creds_json: str) -> None:
    try:
        from google_calendar_sync import GoogleCalendarSync
        cal = GoogleCalendarSync(creds_json=creds_json)
        cal.service.events().delete(calendarId=calendar_id, eventId=gcal_event_id).execute()
        log.info("Google Agenda event %s verwijderd", gcal_event_id)
    except Exception as exc:
        log.warning("Kon Google Agenda event %s niet verwijderen: %s", gcal_event_id, exc)


def _delete_intervals_event(event_id: str, athlete_id: str, api_key: str) -> None:
    try:
        resp = requests.delete(
            f"{INTERVALS_BASE}/{athlete_id}/events/{event_id}",
            auth=("API_KEY", api_key),
            timeout=20,
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    athlete_id   = os.environ.get("INTERVALS_ATHLETE_ID", "").strip()
    api_key      = os.environ.get("INTERVALS_API_KEY", "").strip()
    gist_id      = os.environ.get("GIST_ID", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    gcal_creds   = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
    gcal_cal_id  = os.environ.get("CALENDAR_ID", "").strip()

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
        plan: dict = json.loads(gist_files.get("running_plan.json") or "{}")
    except json.JSONDecodeError:
        plan = {}

    workouts: list[dict] = plan.get("workouts", [])
    cancelled_with_events = [
        w for w in workouts
        if w.get("cancelled") and (w.get("gcal_event_id") or w.get("event_id"))
    ]

    if not cancelled_with_events:
        log.info("Geen geannuleerde workouts met calendar events — niets te doen")
        return

    changed = False
    for workout in cancelled_with_events:
        name = workout.get("name") or workout.get("type") or "workout"
        date = workout.get("date", "?")
        log.info("Verwerken geannuleerde workout: %s op %s", name, date)

        # Verwijder intervals.icu event
        event_id = workout.get("event_id")
        if event_id:
            _delete_intervals_event(event_id, athlete_id, api_key)
            del workout["event_id"]
            changed = True

        # Verwijder Google Agenda event
        gcal_id = workout.get("gcal_event_id")
        if gcal_id and gcal_creds and gcal_cal_id:
            _delete_gcal_event(gcal_id, gcal_cal_id, gcal_creds)
            del workout["gcal_event_id"]
            changed = True
        elif gcal_id and not (gcal_creds and gcal_cal_id):
            log.warning("Google Agenda credentials ontbreken — event %s niet verwijderd", gcal_id)

    if changed:
        _patch_gist(gist_id, github_token, {
            "running_plan.json": json.dumps(plan, indent=2, ensure_ascii=False),
        })
        log.info("Gist bijgewerkt — event IDs verwijderd uit geannuleerde workouts")

    log.info("Klaar.")


if __name__ == "__main__":
    main()
