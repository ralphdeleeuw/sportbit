#!/usr/bin/env python3
"""
SportBit Auto Sign-Up for CrossFit Hilversum

Automatically signs up for Monday and Thursday 20:00 WOD classes.
Run via cron or manually. Dry-run mode enabled by default.

Usage:
    python3 autosignup.py                  # dry-run (default)
    python3 autosignup.py --live           # actually sign up
    python3 autosignup.py --days 7         # look ahead 7 days (default: 7)
    python3 autosignup.py --time 19:00     # target a different time slot
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

BASE_URL = "https://crossfithilversum.sportbitapp.nl/cbm/api/"

# Rooster (schedule) ID: 1 = Hilversum
ROOSTER_ID = 1

# Target schedule: 0=Monday, 3=Thursday (Python weekday numbers)
TARGET_WEEKDAYS = {0: "Monday", 3: "Thursday"}
TARGET_TIME = "20:00"

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
        if resp.status_code == 200:
            log.info("Signed up for event %d.", event_id)
            return True

        log.error("Sign-up failed for event %d: %s %s", event_id, resp.status_code, resp.text[:200])
        return False


# ──────────────────────────────────────────────────────────────
# Core Logic
# ──────────────────────────────────────────────────────────────

def find_target_dates(days_ahead: int) -> list[datetime]:
    """Return upcoming Monday and Thursday dates within the look-ahead window."""
    today = datetime.now().date()
    dates = []
    for offset in range(days_ahead):
        d = today + timedelta(days=offset)
        if d.weekday() in TARGET_WEEKDAYS:
            dates.append(d)
    return dates


def find_target_event(events: list[dict], target_time: str) -> dict | None:
    """Find the WOD event matching the target time (e.g. '20:00')."""
    for event in events:
        start = event.get("start", "")
        # start is like "2026-03-02T20:00:00+01:00"
        if f"T{target_time}:00" in start:
            return event
    return None


def run(username: str, password: str, dry_run: bool, days_ahead: int, target_time: str):
    client = SportBitClient(username, password)

    if not client.login():
        log.error("Aborting: login failed.")
        sys.exit(1)

    target_dates = find_target_dates(days_ahead)
    if not target_dates:
        log.info("No target days (Mon/Thu) in the next %d days.", days_ahead)
        return

    log.info(
        "Checking %d date(s): %s",
        len(target_dates),
        ", ".join(d.strftime("%a %Y-%m-%d") for d in target_dates),
    )

    results = {"signed_up": [], "already": [], "full_waitlist": [], "not_found": [], "failed": []}

    for date in target_dates:
        date_str = date.strftime("%Y-%m-%d")
        day_name = TARGET_WEEKDAYS[date.weekday()]
        log.info("--- %s %s ---", day_name, date_str)

        events = client.get_events(date_str)
        event = find_target_event(events, target_time)

        if not event:
            log.warning("No %s class found on %s.", target_time, date_str)
            results["not_found"].append(date_str)
            continue

        eid = event["id"]
        title = event.get("titel", "?")
        spots = f"{event['aantalDeelnemers']}/{event['maxDeelnemers']}"
        already = event.get("aangemeld", False)
        on_waitlist = event.get("opWachtlijst", False)

        if already:
            log.info("Already signed up for %s at %s (%s) [%s].", title, target_time, spots, eid)
            results["already"].append(date_str)
            continue

        if on_waitlist:
            log.info("Already on waitlist for %s at %s (%s) [%s].", title, target_time, spots, eid)
            results["full_waitlist"].append(date_str)
            continue

        full = event["aantalDeelnemers"] >= event["maxDeelnemers"]
        status = "FULL (waitlist)" if full else "open"

        if dry_run:
            log.info(
                "[DRY RUN] Would sign up for %s at %s (%s, %s) [%s].",
                title, target_time, spots, status, eid,
            )
            results["signed_up"].append(f"{date_str} (dry-run)")
        else:
            log.info("Signing up for %s at %s (%s, %s) [%s] ...", title, target_time, spots, status, eid)
            if client.signup(eid):
                results["signed_up"].append(date_str)
            else:
                results["failed"].append(date_str)

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
    parser.add_argument("--time", default=TARGET_TIME, help=f"Target class time (default: {TARGET_TIME})")
    parser.add_argument("--username", "-u", help="SportBit username (or set SPORTBIT_USERNAME env var)")
    parser.add_argument("--password", "-p", help="SportBit password (or set SPORTBIT_PASSWORD env var)")
    args = parser.parse_args()

    import os
    username = args.username or os.environ.get("SPORTBIT_USERNAME")
    password = args.password or os.environ.get("SPORTBIT_PASSWORD")

    if not username or not password:
        log.error("Provide credentials via --username/--password or SPORTBIT_USERNAME/SPORTBIT_PASSWORD env vars.")
        sys.exit(1)

    dry_run = not args.live
    if dry_run:
        log.info("DRY RUN mode - no sign-ups will be made. Use --live to actually sign up.")

    run(username, password, dry_run, args.days, args.time)


if __name__ == "__main__":
    main()
