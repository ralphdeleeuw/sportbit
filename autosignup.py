#!/usr/bin/env python3
"""
SportBit Auto Sign-Up for CrossFit Hilversum

Automatically signs up for WOD classes on a weekly schedule.
Run via cron or manually. Dry-run mode enabled by default.

Usage:
    python3 autosignup.py                  # dry-run (default)
    python3 autosignup.py --live           # actually sign up
    python3 autosignup.py --days 8         # look ahead 8 days (default: 7)
    python3 autosignup.py --live --sync-calendar  # sign up and sync to Google Calendar
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests

# Import Google Calendar sync
from google_calendar_sync import GoogleCalendarSync

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

BASE_URL = "https://crossfithilversum.sportbitapp.nl/cbm/api/"

# Rooster (schedule) ID: 1 = Hilversum
ROOSTER_ID = 1

# Weekly schedule: list of (weekday_number, time) pairs
# Weekday numbers: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
SCHEDULE = [
    (0, "20:00"),  # Monday 20:00
    (2, "08:00"),  # Wednesday 08:00
    (3, "20:00"),  # Thursday 20:00
    (5, "09:00"),  # Saturday 09:00
]

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sportbit")


# ──────────────────────────────────────────────────────────────
# SportBit Client
# ──────────────────────────────────────────────────────────────

class SportBitClient:
    def __init__(self, username: str, password: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            "Referer": "https://crossfithilversum.sportbitapp.nl/web/nl/events",
        })
        self.username = username
        self.password = password

    def _url(self, path: str) -> str:
        return urljoin(BASE_URL, path)

    def _set_xsrf_header(self):
        """Angular's HttpXsrfInterceptor sends XSRF-TOKEN cookie as X-XSRF-TOKEN header."""
        token = self.session.cookies.get("XSRF-TOKEN")
        if token:
            self.session.headers["X-XSRF-TOKEN"] = token

    def login(self) -> bool:
        """Authenticate and establish session."""
        log.info("Logging in as %s ...", self.username)

        # Hit heartbeat endpoint to get XSRF-TOKEN cookie and session cookies
        self.session.get(self._url("data/heartbeat/"))
        self._set_xsrf_header()

        resp = self.session.post(
            self._url("data/inloggen/"),
            json={"username": self.username, "password": self.password, "remember": True},
        )

        if resp.status_code == 200:
            self._set_xsrf_header()
            log.info("Login successful.")
            return True

        log.error("Login failed: %s %s", resp.status_code, resp.text[:200])
        return False

    def get_events(self, date: str) -> list[dict]:
        """Fetch all events for a given date (YYYY-MM-DD)."""
        resp = self.session.get(
            self._url("data/events/"),
            params={"datum": date, "rooster": ROOSTER_ID},
        )
        resp.raise_for_status()
        data = resp.json()

        # Flatten ochtend/middag/avond into single list
        events = []
        for period in ("ochtend", "middag", "avond"):
            if isinstance(data.get(period), list):
                events.extend(data[period])
        return events

    def signup(self, event_id: int) -> bool:
        """Sign up for an event by ID."""
        self._set_xsrf_header()
        resp = self.session.post(
            self._url(f"data/events/{event_id}/deelname/"),
            json={},
        )
        if resp.status_code in (200, 204):
            log.info("Signed up for event %d.", event_id)
            return True

        log.error("Sign-up failed for event %d: %s %s", event_id, resp.status_code, resp.text[:200])
        return False


# ──────────────────────────────────────────────────────────────
# Google Calendar Helper
# ──────────────────────────────────────────────────────────────

def create_calendar_event(event: dict, date: datetime.date, sync_calendar: bool) -> bool:
    """Create a Google Calendar event for a SportBit signup."""
    if not sync_calendar:
        return True

    try:
        # Get Google credentials from environment
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if not creds_json:
            log.warning("GOOGLE_CREDENTIALS not set; skipping calendar sync.")
            return True

        # Initialize Google Calendar sync
        cal_sync = GoogleCalendarSync(creds_json=creds_json)

        # Extract event details
        title = event.get("titel", "CrossFit WOD")
        start_time = event.get("start", "")  # e.g., "2026-03-02T20:00:00+01:00"

        # Calculate end time: start + 1 hour  <-- FIX
        start_dt = datetime.fromisoformat(start_time)
        end_dt = start_dt + timedelta(hours=1)

        # Build Google Calendar event
        event_details = {
            "summary": title,
            "description": f"SportBit Event ID: {event.get('id')}",
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_dt.isoformat()},  # <-- now 1 hour after start
        }

        # Create the event
        result = cal_sync.create_event(
            calendar_id=os.environ.get("CALENDAR_ID", "primary"),
            event_details=event_details
        )
        log.info("Created Google Calendar event: %s", result.get("id"))
        return True

    except Exception as e:
        log.error("Failed to create Google Calendar event: %s", str(e))
        return False


# ──────────────────────────────────────────────────────────────
# Core Logic
# ──────────────────────────────────────────────────────────────

def find_target_slots(days_ahead: int) -> list[tuple]:
    """Return (date, time) pairs for scheduled classes within the look-ahead window."""
    today = datetime.now().date()
    target_weekdays = {weekday for weekday, _ in SCHEDULE}
    slots = []
    for offset in range(days_ahead +1):
        d = today + timedelta(days=offset)
        if d.weekday() in target_weekdays:
            for weekday, time in SCHEDULE:
                if d.weekday() == weekday:
                    slots.append((d, time))
    return slots


def find_event_at_time(events: list[dict], target_time: str) -> dict | None:
    """Find the WOD event matching the target time (e.g. '20:00')."""
    for event in events:
        start = event.get("start", "")
        # start is like "2026-03-02T20:00:00+01:00"
        if f"T{target_time}:00" in start:
            return event
    return None


def run(username: str, password: str, dry_run: bool, days_ahead: int, sync_calendar: bool):
    client = SportBitClient(username, password)

    if not client.login():
        log.error("Aborting: login failed.")
        sys.exit(1)

    slots = find_target_slots(days_ahead)
    if not slots:
        log.info("No scheduled classes in the next %d days.", days_ahead)
        return

    log.info(
        "Checking %d slot(s): %s",
        len(slots),
        ", ".join(f"{DAY_NAMES[d.weekday()]} {d} {t}" for d, t in slots),
    )

    results = {"signed_up": [], "already": [], "full_waitlist": [], "not_found": [], "failed": []}

    # Cache events per date to avoid duplicate API calls
    events_cache: dict[str, list[dict]] = {}

    for date, target_time in slots:
        date_str = date.strftime("%Y-%m-%d")
        day_name = DAY_NAMES[date.weekday()]
        label = f"{day_name} {date_str} {target_time}"
        log.info("--- %s ---", label)

        if date_str not in events_cache:
            events_cache[date_str] = client.get_events(date_str)
        events = events_cache[date_str]

        event = find_event_at_time(events, target_time)

        if not event:
            log.warning("No %s class found on %s.", target_time, date_str)
            results["not_found"].append(label)
            continue

        eid = event["id"]
        title = event.get("titel", "?")
        spots = f"{event['aantalDeelnemers']}/{event['maxDeelnemers']}"
        already = event.get("aangemeld", False)
        on_waitlist = event.get("opWachtlijst", False)

        if already:
            log.info("Already signed up for %s at %s (%s) [%s].", title, target_time, spots, eid)
            results["already"].append(label)
            continue

        if on_waitlist:
            log.info("Already on waitlist for %s at %s (%s) [%s].", title, target_time, spots, eid)
            results["full_waitlist"].append(label)
            continue

        full = event["aantalDeelnemers"] >= event["maxDeelnemers"]
        status = "FULL (waitlist)" if full else "open"

        if dry_run:
            log.info(
                "[DRY RUN] Would sign up for %s at %s (%s, %s) [%s].",
                title, target_time, spots, status, eid,
            )
            results["signed_up"].append(f"{label} (dry-run)")
        else:
            log.info("Signing up for %s at %s (%s, %s) [%s] ...", title, target_time, spots, status, eid)
            if client.signup(eid):
                results["signed_up"].append(label)
                # Sync to Google Calendar if enabled
                if not create_calendar_event(event, date, sync_calendar):
                    log.warning("Calendar sync failed for %s, but signup was successful.", label)
            else:
                results["failed"].append(label)

    # Summary
    log.info("=== Summary ===")
    if results["signed_up"]:
        log.info("Signed up:    %s", ", ".join(results["signed_up"]))
    if results["already"]:
        log.info("Already in:   %s", ", ".join(results["already"]))
    if results["full_waitlist"]:
        log.info("On waitlist:  %s", ", ".join(results["full_waitlist"]))
    if results["not_found"]:
        log.info("Not found:    %s", ", ".join(results["not_found"]))
    if results["failed"]:
        log.error("Failed:       %s", ", ".join(results["failed"]))


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SportBit auto sign-up for CrossFit Hilversum")
    parser.add_argument("--live", action="store_true", help="Actually sign up (default: dry-run)")
    parser.add_argument("--days", type=int, default=7, help="Days to look ahead (default: 7)")
    parser.add_argument("--sync-calendar", action="store_true", help="Sync successful signups to Google Calendar")
    parser.add_argument("--username", "-u", help="SportBit username (or set SPORTBIT_USERNAME env var)")
    parser.add_argument("--password", "-p", help="SportBit password (or set SPORTBIT_PASSWORD env var)")
    args = parser.parse_args()

    username = args.username or os.environ.get("SPORTBIT_USERNAME")
    password = args.password or os.environ.get("SPORTBIT_PASSWORD")

    if not username or not password:
        log.error("Provide credentials via --username/--password or SPORTBIT_USERNAME/SPORTBIT_PASSWORD env vars.")
        sys.exit(1)

    dry_run = not args.live
    if dry_run:
        log.info("DRY RUN mode - no sign-ups will be made. Use --live to actually sign up.")

    run(username, password, dry_run, args.days, args.sync_calendar)


if __name__ == "__main__":
    main()
