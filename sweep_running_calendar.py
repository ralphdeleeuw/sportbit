#!/usr/bin/env python3
"""
sweep_running_calendar.py — Eenmalige opruiming van opgestapelde hardloop-events
in Google Agenda.

De app maakt running-workout events met een titel die begint met "🏃". Door een
oude bug bleven voltooide events staan. Dit script:
  1. Verwijdert alle 🏃-events met een startdatum in het VERLEDEN.
  2. Ontdubbelt 🏃-events in de TOEKOMST: per dag blijft alleen het nieuwste
     event staan, de rest wordt verwijderd.

Standaard draait dit als DRY RUN (verwijdert niets, logt alleen wat het zou doen).
Zet DRY_RUN=false om daadwerkelijk te verwijderen.

Environment:
  GOOGLE_CREDENTIALS  (vereist)  service-account JSON of pad
  CALENDAR_ID         (vereist)  agenda-id
  DRY_RUN             (optioneel) "true" (default) of "false"
  DAYS_BACK          (optioneel) hoe ver terug scannen (default 540)
  DAYS_FORWARD       (optioneel) hoe ver vooruit scannen (default 90)
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

PREFIX = "🏃"


def _event_start(event: dict) -> datetime | None:
    start = event.get("start", {})
    val = start.get("dateTime") or start.get("date")
    if not val:
        return None
    try:
        # date-only (all-day) → middernacht UTC
        if len(val) == 10:
            return datetime.fromisoformat(val).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    creds = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
    cal_id = os.environ.get("CALENDAR_ID", "").strip()
    if not (creds and cal_id):
        log.error("GOOGLE_CREDENTIALS en CALENDAR_ID zijn vereist")
        sys.exit(1)

    dry_run = os.environ.get("DRY_RUN", "true").strip().lower() != "false"
    days_back = int(os.environ.get("DAYS_BACK", "540"))
    days_forward = int(os.environ.get("DAYS_FORWARD", "90"))

    try:
        from google_calendar_sync import GoogleCalendarSync
        cal = GoogleCalendarSync(creds_json=creds)
    except Exception as exc:
        log.error("Fout bij opzetten Google Agenda service: %s", exc)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=days_back)).isoformat()
    time_max = (now + timedelta(days=days_forward)).isoformat()

    # Alle events ophalen (gepagineerd) en filteren op 🏃-prefix
    running: list[dict] = []
    page_token = None
    while True:
        resp = cal.service.events().list(
            calendarId=cal_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=2500,
            pageToken=page_token,
        ).execute()
        for ev in resp.get("items", []):
            if (ev.get("summary") or "").startswith(PREFIX):
                running.append(ev)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    log.info("%d hardloop-events (🏃) gevonden in venster [-%dd, +%dd]",
             len(running), days_back, days_forward)

    past: list[dict] = []
    future: list[dict] = []
    for ev in running:
        start = _event_start(ev)
        if start is None:
            continue
        (past if start < now else future).append(ev)

    # 1) Alle verleden events verwijderen
    to_delete: list[dict] = list(past)

    # 2) Toekomst ontdubbelen: per dag alleen het nieuwste event behouden
    by_day: dict[str, list[dict]] = {}
    for ev in future:
        start = _event_start(ev)
        day = start.date().isoformat() if start else "?"
        by_day.setdefault(day, []).append(ev)
    dup_count = 0
    for day, evs in by_day.items():
        if len(evs) <= 1:
            continue
        evs.sort(key=lambda e: e.get("created", ""))  # oudste eerst
        keep = evs[-1]
        for ev in evs[:-1]:
            to_delete.append(ev)
            dup_count += 1
        log.info("Dag %s: %d 🏃-events → behoud nieuwste ('%s'), verwijder %d",
                 day, len(evs), keep.get("summary"), len(evs) - 1)

    log.info("Te verwijderen: %d verleden + %d dubbele toekomst = %d totaal",
             len(past), dup_count, len(to_delete))

    deleted = 0
    for ev in to_delete:
        start = _event_start(ev)
        when = start.date().isoformat() if start else "?"
        summary = ev.get("summary", "")
        if dry_run:
            log.info("[DRY RUN] zou verwijderen: %s op %s", summary, when)
            continue
        try:
            cal.service.events().delete(calendarId=cal_id, eventId=ev["id"]).execute()
            log.info("Verwijderd: %s op %s", summary, when)
            deleted += 1
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in (404, 410):
                log.info("Al verwijderd: %s op %s", summary, when)
            else:
                log.warning("Kon event '%s' (%s) niet verwijderen: %s", summary, when, exc)

    if dry_run:
        log.info("DRY RUN — er is niets verwijderd. Zet DRY_RUN=false om door te voeren.")
    else:
        log.info("Klaar — %d event(s) verwijderd.", deleted)


if __name__ == "__main__":
    main()
