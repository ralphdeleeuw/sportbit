#!/usr/bin/env python3
"""
Huppa Auto Sign-Up for CrossFit Hilversum

Automatically signs up for WOD classes on a weekly schedule.
Run via cron or manually. Dry-run mode enabled by default.

Usage:
    python3 autosignup.py                  # dry-run (default)
    python3 autosignup.py --live           # actually sign up
    python3 autosignup.py --days 8         # look ahead 8 days (default: 8)
    python3 autosignup.py --live --sync-calendar  # sign up and sync to Google Calendar

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
from zoneinfo import ZoneInfo

import requests

import notify
from google_calendar_sync import GoogleCalendarSync

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

HUPPA_API_BASE = "https://api.huppa.app"

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
log = logging.getLogger("huppa")


# ──────────────────────────────────────────────────────────────
# Gist State Manager
# ──────────────────────────────────────────────────────────────

class GistStateManager:
    """
    Persists signup state to a GitHub Gist between runs.

    State structure:
    {
        "signed_up": {
            "<occurrence_id>": {
                "date": "2026-03-09",
                "time": "20:00",
                "title": "CrossFit WOD",
                "signed_up_at": "2026-03-02T00:01:00"
            }
        },
        "cancelled": {
            "<occurrence_id>": {
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
                self.state.setdefault("exclusions", {})
                # Prune stale exclusions (past dates)
                today_str = datetime.now(AMS).date().isoformat()
                self.state["exclusions"] = {
                    k: v for k, v in self.state["exclusions"].items()
                    if k[:10] >= today_str
                }
                log.info(
                    "Loaded state: %d signed up, %d cancelled, %d exclusions.",
                    len(self.state["signed_up"]),
                    len(self.state["cancelled"]),
                    len(self.state["exclusions"]),
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

    def is_excluded(self, date: str, time: str) -> bool:
        return f"{date}_{time}" in self.state.get("exclusions", {})

    def is_cancelled(self, occurrence_id: str) -> bool:
        return str(occurrence_id) in self.state["cancelled"]

    def is_signed_up_by_script(self, occurrence_id: str) -> bool:
        return str(occurrence_id) in self.state["signed_up"]

    def mark_signed_up(self, occurrence_id: str, date: str, time: str, title: str):
        self.state["signed_up"][str(occurrence_id)] = {
            "date": date,
            "time": time,
            "title": title,
            "signed_up_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save()

    def mark_cancelled(self, occurrence_id: str, date: str, time: str, title: str):
        self.state["cancelled"][str(occurrence_id)] = {
            "date": date,
            "time": time,
            "title": title,
            "cancelled_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.state["signed_up"].pop(str(occurrence_id), None)
        self._save()

    def batch_update_capacity(self, capacity_updates: dict[str, dict]) -> None:
        """Update class capacity data for multiple slots and save once.

        capacity_updates: {"YYYY-MM-DD_HH:MM": {"available": int, "is_full": bool}}
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
                still_registered = event.get("is_booked", False)
                if not still_registered:
                    title = event.get("name", "?")
                    starts_at = event.get("starts_at", "")
                    date_str = starts_at[:10] if starts_at else "?"
                    time_str = starts_at[11:16] if len(starts_at) > 15 else "?"
                    log.info(
                        "Detected manual cancellation for occurrence %s (%s %s %s).",
                        eid, title, date_str, time_str,
                    )
                    self.mark_cancelled(eid, date_str, time_str, title)
                    newly_cancelled.append(eid)
        if newly_cancelled:
            log.info("Marked %d occurrence(s) as manually cancelled.", len(newly_cancelled))
        return newly_cancelled


# ──────────────────────────────────────────────────────────────
# Huppa Client
# ──────────────────────────────────────────────────────────────

class HuppaClient:
    def __init__(self, email: str, password: str, subdomain: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Subdomain": subdomain,
            "Origin": f"https://{subdomain}.huppa.app",
            "Referer": f"https://{subdomain}.huppa.app/",
        })
        self.email = email
        self.password = password
        self.subdomain = subdomain

    def login(self) -> bool:
        log.info("Logging in to Huppa as %s ...", self.email)
        resp = self.session.post(
            f"{HUPPA_API_BASE}/auth/login",
            json={"email": self.email, "password": self.password},
            timeout=20,
        )
        if resp.status_code == 200:
            log.info("Huppa login successful.")
            return True
        log.error("Huppa login failed: %s %s", resp.status_code, resp.text[:200])
        return False

    def _get_with_reauth(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.get(url, **kwargs)
        if resp.status_code == 401:
            log.info("Session expired, re-authenticating...")
            self.login()
            resp = self.session.get(url, **kwargs)
        return resp

    @staticmethod
    def _normalize_event(evt: dict) -> dict:
        """Convert camelCase API fields to snake_case with Amsterdam-local datetime strings."""
        def parse_utc(s: str) -> str:
            if not s:
                return ""
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone(AMS).strftime("%Y-%m-%d %H:%M")

        return {
            "id": evt.get("id"),
            "name": evt.get("name", "CrossFit WOD"),
            "starts_at": parse_utc(evt.get("startsAt", "")),
            "ends_at": parse_utc(evt.get("endsAt", "")),
            "available_slots": evt.get("availableSlots", 0),
            "is_full": evt.get("isFull", False),
            "is_booked": evt.get("isBooked", False),
            "is_on_waitlist": evt.get("isOnWaitlist", False),
            "is_eligible_to_book": evt.get("isEligibleToBook", True),
            "organization_id": (evt.get("category") or {}).get("organizationId"),
        }

    def get_events(self, date: str) -> list[dict]:
        resp = self._get_with_reauth(
            f"{HUPPA_API_BASE}/users/me/occurrences",
            params={"date": date},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data if isinstance(data, list) else data.get("data", data.get("occurrences", []))
        normalized = [self._normalize_event(e) for e in raw]
        log.debug("Fetched %d events for %s: %s", len(normalized), date,
                  [(e["starts_at"], e["name"]) for e in normalized])
        return normalized

    def signup(self, event: dict) -> bool:
        org_id = event.get("organization_id")
        occ_id = event.get("id")
        if not org_id or not occ_id:
            log.error("Cannot sign up: missing organization_id or id in event %s", event)
            return False
        resp = self.session.post(
            f"{HUPPA_API_BASE}/organizations/{org_id}/occurrences/{occ_id}/booking",
            json={},
            timeout=20,
        )
        if resp.status_code in (200, 201, 204):
            log.info("Signed up for occurrence %s.", occ_id)
            return True
        log.error("Sign-up failed for occurrence %s: %s %s", occ_id, resp.status_code, resp.text[:200])
        return False

    def cancel(self, event: dict) -> bool:
        org_id = event.get("organization_id")
        occ_id = event.get("id")
        if not org_id or not occ_id:
            log.error("Cannot cancel: missing organization_id or id in event %s", event)
            return False
        resp = self.session.delete(
            f"{HUPPA_API_BASE}/organizations/{org_id}/occurrences/{occ_id}/booking",
            timeout=20,
        )
        if resp.status_code in (200, 204):
            log.info("Cancelled booking for occurrence %s.", occ_id)
            return True
        log.error("Cancel failed for occurrence %s: %s %s", occ_id, resp.status_code, resp.text[:200])
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
        title = event.get("name", "CrossFit WOD")
        starts_at = event.get("starts_at", "")

        # Huppa returns "YYYY-MM-DD HH:MM" in Amsterdam time — add timezone for Google Calendar
        start_dt = datetime.fromisoformat(starts_at).replace(tzinfo=AMS)
        end_dt = start_dt + timedelta(hours=1)

        event_details = {
            "summary": title,
            "description": f"Huppa Occurrence ID: {event.get('id')}",
            "start": {"dateTime": start_dt.isoformat()},
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


def delete_calendar_event(occurrence_id: str, sync_calendar: bool) -> bool:
    if not sync_calendar:
        return True

    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if not creds_json:
            log.warning("GOOGLE_CREDENTIALS not set; skipping calendar delete.")
            return True

        cal_sync = GoogleCalendarSync(creds_json=creds_json)
        calendar_id = os.environ.get("CALENDAR_ID", "primary")
        calendar_events = cal_sync.find_events_by_huppa_id(occurrence_id, calendar_id)

        if not calendar_events:
            log.info("No Google Calendar event found for Huppa occurrence %s.", occurrence_id)
            return True

        for cal_event in calendar_events:
            cal_sync.delete_event(cal_event["id"], calendar_id)
            log.info("Deleted Google Calendar event %s for Huppa occurrence %s.", cal_event["id"], occurrence_id)

        return True

    except Exception as e:
        log.error("Failed to delete Google Calendar event for Huppa occurrence %s: %s", occurrence_id, str(e))
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


def find_event_at_time(events: list[dict], date_str: str, target_time: str) -> dict | None:
    # Huppa starts_at format: "YYYY-MM-DD HH:MM"
    # Prefer an event the athlete is already signed up for at this time,
    # so we don't accidentally try to sign up for CrossFit when they already
    # enrolled in Open Gym (or another class) at the same slot.
    prefix = f"{date_str} {target_time}"
    for event in events:
        starts_at = event.get("starts_at", "")
        if starts_at.startswith(prefix) and event.get("is_booked", False):
            return event
    for event in events:
        starts_at = event.get("starts_at", "")
        if starts_at.startswith(prefix):
            return event
    return None


def send_weekly_summary(email: str, password: str, subdomain: str):
    client = HuppaClient(email, password, subdomain)
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
            if not event.get("is_booked", False) and not event.get("is_on_waitlist", False):
                continue
            starts_at = event.get("starts_at", "")
            time_str = starts_at[11:16] if len(starts_at) > 15 else "?"
            title = event.get("name", "CrossFit WOD")
            available = event.get("available_slots", "?")
            on_waitlist = event.get("is_on_waitlist", False)
            status = "⏳ wachtlijst" if on_waitlist else "✅ ingeschreven"
            day_name_nl = day_names_nl[d.weekday()]
            spots_str = f"{available} vrij" if available != "?" else ""
            registered_events.append((d, time_str, f"{day_name_nl} {d.strftime('%d/%m')} {time_str} — {title} ({spots_str}) {status}"))

    if not registered_events:
        log.info("Geen inschrijvingen gevonden voor de komende week.")
        message = "Komende week: geen inschrijvingen."
        notify.send_notification("CrossFit week overzicht 📅", message)
        return

    registered_events.sort(key=lambda x: (x[0], x[1]))
    lines = [line for _, _, line in registered_events]
    message = "Komende week:\n" + "\n".join(lines)
    log.info("Weekly summary:\n%s", message)
    notify.send_notification("CrossFit week overzicht 📅", message)


def run(email: str, password: str, subdomain: str, dry_run: bool, days_ahead: int,
        sync_calendar: bool, state: GistStateManager | None):
    client = HuppaClient(email, password, subdomain)

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
    capacity_updates: dict[str, dict] = {}  # {"YYYY-MM-DD_HH:MM": {"available": int, "is_full": bool}}

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
        # Also scan upcoming non-scheduled days that have signed_up events,
        # so manual cancellations on those days are detected.
        today_str = today.strftime("%Y-%m-%d")
        signed_up_dates = {
            info["date"]
            for info in state.state["signed_up"].values()
            if info["date"] >= today_str
        }
        for date_str in signed_up_dates:
            if date_str not in events_cache:
                try:
                    events_cache[date_str] = client.get_events(date_str)
                except Exception as exc:
                    log.warning("Could not fetch events for %s: %s", date_str, exc)
                    events_cache[date_str] = []
            all_events.extend(events_cache[date_str])
        newly_cancelled = state.detect_manual_cancellations(all_events)
        for eid in newly_cancelled:
            delete_calendar_event(eid, sync_calendar)

    for date, target_time in slots:
        date_str = date.strftime("%Y-%m-%d")
        day_name = DAY_NAMES[date.weekday()]
        label = f"{day_name} {date_str} {target_time}"
        log.info("--- %s ---", label)

        if state and state.is_excluded(date_str, target_time):
            log.info("Skipping %s — excluded by user.", label)
            results["skipped"].append(f"{label} (excluded)")
            continue

        if date_str not in events_cache:
            events_cache[date_str] = client.get_events(date_str)
        events = events_cache[date_str]

        event = find_event_at_time(events, date_str, target_time)

        if not event:
            log.warning("No %s class found on %s.", target_time, date_str)
            results["not_found"].append(label)
            continue

        eid = str(event["id"])
        title = event.get("name", "?")
        available_slots = event.get("available_slots", 0)
        is_full = event.get("is_full", False)
        spots = f"{available_slots} vrij" if not is_full else "vol"
        already = event.get("is_booked", False)
        on_waitlist = event.get("is_on_waitlist", False)
        # Track capacity for the dashboard
        capacity_updates[f"{date_str}_{target_time}"] = {
            "available": available_slots,
            "is_full": is_full,
        }

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

        status = "vol (wachtlijst)" if is_full else "open"

        if dry_run:
            log.info(
                "[DRY RUN] Would sign up for %s at %s (%s, %s) [%s].",
                title, target_time, spots, status, eid,
            )
            results["signed_up"].append(f"{label} (dry-run)")
        else:
            log.info("Signing up for %s at %s (%s, %s) [%s] ...", title, target_time, spots, status, eid)
            if client.signup(event):
                results["signed_up"].append(label)
                if state:
                    state.mark_signed_up(eid, date_str, target_time, title)
                notify.send_notification(
                    "CrossFit Inschrijving ✅",
                    f"Ingeschreven voor {title} op {day_name} {date_str} om {target_time} 💪",
                )
                if not create_calendar_event(event, date, sync_calendar):
                    log.warning("Calendar sync failed for %s, but signup was successful.", label)
            else:
                results["failed"].append(label)

    # Persist capacity data to gist (single save for all slots)
    if state and capacity_updates:
        state.batch_update_capacity(capacity_updates)

    # Scan ALL upcoming days for manual enrollments, including today and scheduled days.
    # On scheduled days the main loop only handles the one targeted slot; any
    # other manually enrolled class (e.g. Open Gym at a different time) is detected here.
    for offset in range(0, days_ahead + 1):
        d = today + timedelta(days=offset)
        date_str = d.strftime("%Y-%m-%d")
        if date_str not in events_cache:
            events_cache[date_str] = client.get_events(date_str)
        for event in events_cache[date_str]:
            if not event.get("is_booked", False):
                continue
            eid = str(event["id"])
            if state and state.is_signed_up_by_script(eid):
                continue
            title = event.get("name", "?")
            starts_at = event.get("starts_at", "")
            time_str = starts_at[11:16] if len(starts_at) > 15 else "?"
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
    parser = argparse.ArgumentParser(description="Huppa auto sign-up for CrossFit Hilversum")
    parser.add_argument("--live", action="store_true", help="Actually sign up (default: dry-run)")
    parser.add_argument("--days", type=int, default=8, help="Days to look ahead (default: 8)")
    parser.add_argument("--sync-calendar", action="store_true", help="Sync successful signups to Google Calendar")
    parser.add_argument("--email", "-e", help="Huppa email (or set HUPPA_EMAIL env var)")
    parser.add_argument("--password", "-p", help="Huppa password (or set HUPPA_PASSWORD env var)")
    parser.add_argument("--subdomain", "-s", help="Huppa gym subdomain (or set HUPPA_SUBDOMAIN env var)")
    parser.add_argument("--test-notification", action="store_true", help="Stuur een testnotificatie en stop")
    parser.add_argument("--weekly-summary", action="store_true", help="Stuur een weekoverzicht en stop")
    args = parser.parse_args()

    email = args.email or os.environ.get("HUPPA_EMAIL")
    password = args.password or os.environ.get("HUPPA_PASSWORD")
    subdomain = args.subdomain or os.environ.get("HUPPA_SUBDOMAIN")

    if args.test_notification:
        log.info("Sending test notification...")
        success = notify.send_notification("Huppa Test 🎉", "Dit is een testbericht van Huppa")
        sys.exit(0 if success else 1)

    # Weekly summary mode
    if args.weekly_summary:
        if not email or not password or not subdomain:
            log.error("Provide credentials via --email/--password/--subdomain or HUPPA_EMAIL/HUPPA_PASSWORD/HUPPA_SUBDOMAIN env vars.")
            sys.exit(1)
        send_weekly_summary(email, password, subdomain)
        sys.exit(0)

    if not email or not password or not subdomain:
        log.error("Provide credentials via --email/--password/--subdomain or HUPPA_EMAIL/HUPPA_PASSWORD/HUPPA_SUBDOMAIN env vars.")
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

    run(email, password, subdomain, dry_run, args.days, args.sync_calendar, state)


if __name__ == "__main__":
    main()
