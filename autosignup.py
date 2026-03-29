#!/usr/bin/env python3
"""
SportBit Auto Sign-Up for CrossFit Hilversum

Automatically signs up for WOD classes on a weekly schedule.
Run via cron or manually. Dry-run mode enabled by default.

Usage:
    python3 autosignup.py                  # dry-run (default)
    python3 autosignup.py --live           # actually sign up
    python3 autosignup.py --days 8         # look ahead 8 days (default: 8)
    python3 autosignup.py --live --sync-calendar  # sign up and sync to Google Calendar
    python3 autosignup.py --live --force   # skip timezone check (for manual runs)

State management:
    A GitHub Gist is used to persist state between runs (signed up / manually cancelled events).
    Set GIST_ID and GITHUB_TOKEN environment variables.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

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
    (6, "09:00"),  # Sunday 09:00
]

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Gist filename for state storage
GIST_FILENAME = "sportbit_state.json"

# Amsterdam timezone
AMS = ZoneInfo("Europe/Amsterdam")

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
# Timezone check
# ──────────────────────────────────────────────────────────────

def is_after_midnight_amsterdam() -> bool:
    """
    Returns True if the current Amsterdam time is between 00:00 and 00:59.
    This ensures the script only runs once per day just after midnight,
    regardless of summer/winter time (CET/CEST). The full hour window
    accounts for GitHub Actions scheduling delays.
    """
    now = datetime.now(AMS)
    return now.hour == 0


# ──────────────────────────────────────────────────────────────
# Gist State Manager
# ──────────────────────────────────────────────────────────────

class GistStateManager:
    """
    Persists signup state to a GitHub Gist between runs.

    State structure:
    {
        "signed_up": {
            "<event_id>": {
                "date": "2026-03-09",
                "time": "20:00",
                "title": "CrossFit WOD",
                "signed_up_at": "2026-03-02T00:01:00"
            }
        },
        "cancelled": {
            "<event_id>": {
                "date": "2026-03-09",
                "time": "20:00",
                "title": "CrossFit WOD",
                "cancelled_at": "2026-03-02T12:00:00"
            }
        }
    }
    """

    def __init__(self, gist_id: str, github_token: str):
        self.gist_id = gist_id
        self.headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github+json",
        }
        self.state = {"signed_up": {}, "cancelled": {}}
        self._load()

    def _load(self):
        """Load state from Gist."""
        try:
            resp = requests.get(
                f"https://api.github.com/gists/{self.gist_id}",
                headers=self.headers,
                timeout=10,
            )
            resp.raise_for_status()
            files = resp.json().get("files", {})
            if GIST_FILENAME in files:
                content = files[GIST_FILENAME].get("content", "{}")
                self.state = json.loads(content)
                self.state.setdefault("signed_up", {})
                self.state.setdefault("cancelled", {})
                log.info(
                    "Loaded state: %d signed up, %d cancelled.",
                    len(self.state["signed_up"]),
                    len(self.state["cancelled"]),
                )
            else:
                log.info("No existing state found in Gist; starting fresh.")
        except Exception as e:
            log.error("Failed to load state from Gist: %s", e)

    def _save(self):
        """Save state to Gist."""
        try:
            resp = requests.patch(
                f"https://api.github.com/gists/{self.gist_id}",
                headers=self.headers,
                json={"files": {GIST_FILENAME: {"content": json.dumps(self.state, indent=2)}}},
                timeout=10,
            )
            resp.raise_for_status()
            log.info("State saved to Gist.")
        except Exception as e:
            log.error("Failed to save state to Gist: %s", e)

    def is_cancelled(self, event_id: int) -> bool:
        return str(event_id) in self.state["cancelled"]

    def is_signed_up_by_script(self, event_id: int) -> bool:
        return str(event_id) in self.state["signed_up"]

    def mark_signed_up(self, event_id: int, date: str, time: str, title: str):
        self.state["signed_up"][str(event_id)] = {
            "date": date,
            "time": time,
            "title": title,
            "signed_up_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save()

    def mark_cancelled(self, event_id: int, date: str, time: str, title: str):
        self.state["cancelled"][str(event_id)] = {
            "date": date,
            "time": time,
            "title": title,
            "cancelled_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.state["signed_up"].pop(str(event_id), None)
        self._save()

    def batch_update_capacity(self, capacity_updates: dict[str, dict]) -> None:
        """Update class capacity data for multiple slots and save once.

        capacity_updates: {"YYYY-MM-DD_HH:MM": {"current": int, "max": int}}
        """
        if not capacity_updates:
            return
        self.state.setdefault("class_capacity", {})
        checked_at = datetime.now().isoformat(timespec="seconds")
        for key, data in capacity_updates.items():
            self.state["class_capacity"][key] = {
                **data,
                "checked_at": checked_at,
            }
        # Keep only the last 90 days of capacity data
        cutoff = (datetime.now().date() - timedelta(days=90)).isoformat()
        self.state["class_capacity"] = {
            k: v for k, v in self.state["class_capacity"].items()
            if k[:10] >= cutoff
        }
        self._save()
        log.info("Capacity data updated for %d slots.", len(capacity_updates))

    def detect_manual_cancellations(self, events: list[dict]):
        newly_cancelled = []
        for event in events:
            eid = str(event["id"])
            if eid in self.state["signed_up"] and eid not in self.state["cancelled"]:
                still_registered = event.get("aangemeld", False)
                if not still_registered:
                    title = event.get("titel", "?")
                    start = event.get("start", "")
                    date_str = start[:10] if start else "?"
                    time_str = start[11:16] if len(start) > 15 else "?"
                    log.info(
                        "Detected manual cancellation for event %s (%s %s %s).",
                        eid, title, date_str, time_str,
                    )
                    self.mark_cancelled(int(eid), date_str, time_str, title)
                    newly_cancelled.append(eid)
        if newly_cancelled:
            log.info("Marked %d event(s) as manually cancelled.", len(newly_cancelled))
        return newly_cancelled


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
        token = self.session.cookies.get("XSRF-TOKEN")
        if token:
            self.session.headers["X-XSRF-TOKEN"] = token

    def login(self) -> bool:
        log.info("Logging in as %s ...", self.username)
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
        resp = self.session.get(
            self._url("data/events/"),
            params={"datum": date, "rooster": ROOSTER_ID},
        )
        resp.raise_for_status()
        data = resp.json()

        events = []
        for period in ("ochtend", "middag", "avond"):
            if isinstance(data.get(period), list):
                events.extend(data[period])
        return events

    def signup(self, event_id: int) -> bool:
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

def create_calendar_event(event: dict, date: datetime, sync_calendar: bool) -> bool:
    if not sync_calendar:
        return True

    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if not creds_json:
            log.warning("GOOGLE_CREDENTIALS not set; skipping calendar sync.")
            return True

        cal_sync = GoogleCalendarSync(creds_json=creds_json)
        title = event.get("titel", "CrossFit WOD")
        start_time = event.get("start", "")
        start_dt = datetime.fromisoformat(start_time)
        end_dt = start_dt + timedelta(hours=1)

        event_details = {
            "summary": title,
            "description": f"SportBit Event ID: {event.get('id')}",
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_dt.isoformat()},
        }

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
# Pushover Notifications
# ──────────────────────────────────────────────────────────────

def send_pushover_notification(message: str) -> bool:
    user_key = os.environ.get("PUSHOVER_USER_KEY")
    api_token = os.environ.get("PUSHOVER_API_TOKEN")

    if not user_key or not api_token:
        log.warning("PUSHOVER_USER_KEY or PUSHOVER_API_TOKEN not set; skipping notification.")
        return False

    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            json={
                "token": api_token,
                "user": user_key,
                "title": "CrossFit Inschrijving ✅",
                "message": message,
            },
            timeout=10,
        )
        resp.raise_for_status()
        log.info("Pushover notification sent.")
        return True
    except Exception as e:
        log.error("Failed to send Pushover notification: %s", e)
        return False


# ──────────────────────────────────────────────────────────────
# Core Logic
# ──────────────────────────────────────────────────────────────

def find_target_slots(days_ahead: int) -> list[tuple]:
    """Return (date, time) pairs for scheduled classes within the look-ahead window."""
    today = datetime.now(AMS).date()
    target_weekdays = {weekday for weekday, _ in SCHEDULE}
    slots = []
    for offset in range(1, days_ahead + 1):  # Start bij 1 om vandaag over te slaan
        d = today + timedelta(days=offset)
        if d.weekday() in target_weekdays:
            for weekday, time in SCHEDULE:
                if d.weekday() == weekday:
                    slots.append((d, time))
    return slots


def find_event_at_time(events: list[dict], target_time: str) -> dict | None:
    for event in events:
        start = event.get("start", "")
        if f"T{target_time}:00" in start:
            return event
    return None


def send_weekly_summary(username: str, password: str):
    client = SportBitClient(username, password)
    if not client.login():
        log.error("Aborting: login failed.")
        sys.exit(1)

    today = datetime.now(AMS).date()
    day_names_nl = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]

    # Collect all registered events for the coming week by scanning every day.
    # This captures both auto-scheduled registrations and manual sign-ups/cancellations.
    registered_events = []
    for offset in range(1, 8):
        d = today + timedelta(days=offset)
        date_str = d.strftime("%Y-%m-%d")
        try:
            events = client.get_events(date_str)
        except Exception as exc:
            log.warning("Could not fetch events for %s: %s", date_str, exc)
            continue
        for event in events:
            if not event.get("aangemeld", False) and not event.get("opWachtlijst", False):
                continue
            start = event.get("start", "")
            time_str = start[11:16] if len(start) > 15 else "?"
            title = event.get("titel", "CrossFit WOD")
            spots = f"{event['aantalDeelnemers']}/{event['maxDeelnemers']}"
            on_waitlist = event.get("opWachtlijst", False)
            status = "⏳ wachtlijst" if on_waitlist else "✅ ingeschreven"
            day_name_nl = day_names_nl[d.weekday()]
            registered_events.append((d, time_str, f"{day_name_nl} {d.strftime('%d/%m')} {time_str} — {title} ({spots}) {status}"))

    if not registered_events:
        log.info("Geen inschrijvingen gevonden voor de komende week.")
        message = "Komende week: geen inschrijvingen."
        send_pushover_notification_summary(message)
        return

    registered_events.sort(key=lambda x: (x[0], x[1]))
    lines = [line for _, _, line in registered_events]
    message = "Komende week:\n" + "\n".join(lines)
    log.info("Weekly summary:\n%s", message)
    send_pushover_notification_summary(message)


def send_pushover_notification_summary(message: str) -> bool:
    user_key = os.environ.get("PUSHOVER_USER_KEY")
    api_token = os.environ.get("PUSHOVER_API_TOKEN")

    if not user_key or not api_token:
        log.warning("PUSHOVER_USER_KEY or PUSHOVER_API_TOKEN not set; skipping notification.")
        return False

    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            json={
                "token": api_token,
                "user": user_key,
                "title": "CrossFit week overzicht 📅",
                "message": message,
            },
            timeout=10,
        )
        resp.raise_for_status()
        log.info("Pushover weekly summary sent.")
        return True
    except Exception as e:
        log.error("Failed to send Pushover notification: %s", e)
        return False


def run(username: str, password: str, dry_run: bool, days_ahead: int, sync_calendar: bool,
        state: GistStateManager | None):
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

    results = {"signed_up": [], "already": [], "full_waitlist": [], "not_found": [], "failed": [], "skipped": []}

    events_cache: dict[str, list[dict]] = {}
    capacity_updates: dict[str, dict] = {}  # {"YYYY-MM-DD_HH:MM": {"current": int, "max": int}}

    # First pass: fetch events and detect manual cancellations.
    # Scan BOTH upcoming slots AND recent past scheduled days (last 14 days)
    # so that late cancellations for already-passed classes are picked up.
    today = datetime.now(AMS).date()

    if state:
        all_events = []
        scheduled_weekdays = {weekday for weekday, _ in SCHEDULE}
        # Past 14 days: check every scheduled weekday
        for offset in range(1, 15):
            d = today - timedelta(days=offset)
            if d.weekday() not in scheduled_weekdays:
                continue
            date_str = d.strftime("%Y-%m-%d")
            if date_str not in events_cache:
                try:
                    events_cache[date_str] = client.get_events(date_str)
                except Exception as exc:
                    log.warning("Could not fetch past events for %s: %s", date_str, exc)
                    events_cache[date_str] = []
            all_events.extend(events_cache[date_str])
        # Upcoming slots
        for date, _ in slots:
            date_str = date.strftime("%Y-%m-%d")
            if date_str not in events_cache:
                events_cache[date_str] = client.get_events(date_str)
            all_events.extend(events_cache[date_str])
        state.detect_manual_cancellations(all_events)

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
        current_cap = event.get("aantalDeelnemers", 0)
        max_cap = event.get("maxDeelnemers", 0)
        spots = f"{current_cap}/{max_cap}"
        already = event.get("aangemeld", False)
        on_waitlist = event.get("opWachtlijst", False)
        # Track capacity for the dashboard
        capacity_updates[f"{date_str}_{target_time}"] = {"current": current_cap, "max": max_cap}

        if state and state.is_cancelled(eid):
            log.info("Skipping %s at %s — manually cancelled. [%s]", title, target_time, eid)
            results["skipped"].append(f"{label} (manually cancelled)")
            continue

        if already:
            log.info("Already signed up for %s at %s (%s) [%s].", title, target_time, spots, eid)
            results["already"].append(label)
            if state and not state.is_signed_up_by_script(eid):
                state.mark_signed_up(eid, date_str, target_time, title)
                if not create_calendar_event(event, date, sync_calendar):
                    log.warning("Calendar sync failed for manually enrolled %s.", label)
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
                if state:
                    state.mark_signed_up(eid, date_str, target_time, title)
                send_pushover_notification(
                    f"Ingeschreven voor {title} op {day_name} {date_str} om {target_time} 💪"
                )
                if not create_calendar_event(event, date, sync_calendar):
                    log.warning("Calendar sync failed for %s, but signup was successful.", label)
            else:
                results["failed"].append(label)

    # Persist capacity data to gist (single save for all slots)
    if state and capacity_updates:
        state.batch_update_capacity(capacity_updates)

    # Scan non-scheduled days for manual enrollments
    scheduled_weekdays = {weekday for weekday, _ in SCHEDULE}
    for offset in range(1, days_ahead + 1):
        d = today + timedelta(days=offset)
        if d.weekday() in scheduled_weekdays:
            continue  # Already handled above
        date_str = d.strftime("%Y-%m-%d")
        if date_str not in events_cache:
            events_cache[date_str] = client.get_events(date_str)
        for event in events_cache[date_str]:
            if not event.get("aangemeld", False):
                continue
            eid = event["id"]
            if state and state.is_signed_up_by_script(eid):
                continue
            title = event.get("titel", "?")
            start = event.get("start", "")
            time_str = start[11:16] if len(start) > 15 else "?"
            day_name = DAY_NAMES[d.weekday()]
            label = f"{day_name} {date_str} {time_str}"
            log.info("Detected manual enrollment for %s at %s [%s].", title, label, eid)
            if state:
                state.mark_signed_up(eid, date_str, time_str, title)
            if not create_calendar_event(event, d, sync_calendar):
                log.warning("Calendar sync failed for manually enrolled %s.", label)
            results["already"].append(f"{label} (manual)")

    # Summary
    log.info("=== Summary ===")
    if results["signed_up"]:
        log.info("Signed up:           %s", ", ".join(results["signed_up"]))
    if results["already"]:
        log.info("Already in:          %s", ", ".join(results["already"]))
    if results["full_waitlist"]:
        log.info("On waitlist:         %s", ", ".join(results["full_waitlist"]))
    if results["skipped"]:
        log.info("Skipped (cancelled): %s", ", ".join(results["skipped"]))
    if results["not_found"]:
        log.info("Not found:           %s", ", ".join(results["not_found"]))
    if results["failed"]:
        log.error("Failed:              %s", ", ".join(results["failed"]))


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SportBit auto sign-up for CrossFit Hilversum")
    parser.add_argument("--live", action="store_true", help="Actually sign up (default: dry-run)")
    parser.add_argument("--days", type=int, default=8, help="Days to look ahead (default: 8)")
    parser.add_argument("--sync-calendar", action="store_true", help="Sync successful signups to Google Calendar")
    parser.add_argument("--username", "-u", help="SportBit username (or set SPORTBIT_USERNAME env var)")
    parser.add_argument("--password", "-p", help="SportBit password (or set SPORTBIT_PASSWORD env var)")
    parser.add_argument("--test-notification", action="store_true", help="Stuur een testnotificatie via Pushover en stop")
    parser.add_argument("--force", action="store_true", help="Sla tijdzone check over (voor handmatige runs)")
    parser.add_argument("--weekly-summary", action="store_true", help="Stuur een weekoverzicht via Pushover en stop")
    args = parser.parse_args()

    # Weekly summary mode
    if args.weekly_summary:
        username = args.username or os.environ.get("SPORTBIT_USERNAME")
        password = args.password or os.environ.get("SPORTBIT_PASSWORD")
        if not username or not password:
            log.error("Provide credentials via --username/--password or SPORTBIT_USERNAME/SPORTBIT_PASSWORD env vars.")
            sys.exit(1)
        send_weekly_summary(username, password)
        sys.exit(0)

    # Test notification mode: geen credentials nodig
    if args.test_notification:
        log.info("Sending test Pushover notification...")
        success = send_pushover_notification("Dit is een testbericht van SportBit 🎉")
        sys.exit(0 if success else 1)

    # Tijdzone check: alleen uitvoeren net na middernacht Amsterdam tijd
    if not args.force:
        if not is_after_midnight_amsterdam():
            now = datetime.now(AMS)
            log.info(
                "Huidige Amsterdam tijd is %s — niet na middernacht. Gebruik --force om dit over te slaan.",
                now.strftime("%H:%M"),
            )
            sys.exit(0)
        else:
            log.info("Amsterdam tijd check OK: %s", datetime.now(AMS).strftime("%H:%M"))

    username = args.username or os.environ.get("SPORTBIT_USERNAME")
    password = args.password or os.environ.get("SPORTBIT_PASSWORD")

    if not username or not password:
        log.error("Provide credentials via --username/--password or SPORTBIT_USERNAME/SPORTBIT_PASSWORD env vars.")
        sys.exit(1)

    # Initialize Gist state manager if configured
    gist_id = os.environ.get("GIST_ID")
    github_token = os.environ.get("GITHUB_TOKEN")
    state = None
    if gist_id and github_token:
        log.info("Gist state management enabled (Gist ID: %s).", gist_id)
        state = GistStateManager(gist_id, github_token)
    else:
        log.warning("GIST_ID or GITHUB_TOKEN not set; state management disabled.")

    dry_run = not args.live
    if dry_run:
        log.info("DRY RUN mode - no sign-ups will be made. Use --live to actually sign up.")

    run(username, password, dry_run, args.days, args.sync_calendar, state)


if __name__ == "__main__":
    main()
