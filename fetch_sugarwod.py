#!/usr/bin/env python3
"""
SugarWOD WOD Fetcher for CrossFit Hilversum

Logs in to SugarWOD with email/password, fetches the calendar page for this
week and next week, parses the workout data per day, and stores it in a
GitHub Gist for display in the SportBit dashboard.

Usage:
    python3 fetch_sugarwod.py

Environment variables:
    SUGARWOD_EMAIL    - SugarWOD account email (required)
    SUGARWOD_PASSWORD - SugarWOD account password (required)
    GIST_ID          - GitHub Gist ID for storing WOD data
    GITHUB_TOKEN     - GitHub personal access token with gist scope
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

SUGARWOD_BASE = "https://app.sugarwod.com"
GIST_FILENAME = "sugarwod_wod.json"
AMS = ZoneInfo("Europe/Amsterdam")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sugarwod")


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def get_monday(dt: datetime) -> datetime:
    """Return Monday of the week containing dt (time stripped)."""
    d = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())


# ──────────────────────────────────────────────────────────────
# Login
# ──────────────────────────────────────────────────────────────

def login(session: requests.Session, email: str, password: str) -> bool:
    """
    Log in to SugarWOD.  Parses the sign-in form automatically so it is
    resilient to field-name changes.  Returns True on success.
    """
    sign_in_url = f"{SUGARWOD_BASE}/athletes/sign_in"

    resp = session.get(sign_in_url, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find the login form
    form = soup.find("form", action=re.compile(r"sign_in", re.I))
    if form is None:
        form = soup.find("form")

    if form is None:
        log.error("Could not find login form on sign-in page")
        return False

    # Collect all hidden inputs (CSRF token, etc.)
    form_data: dict[str, str] = {}
    for inp in form.find_all("input", type="hidden"):
        name = inp.get("name", "")
        value = inp.get("value", "")
        if name:
            form_data[name] = value

    # Also check <meta name="csrf-token"> as fallback
    if not any("csrf" in k.lower() for k in form_data):
        meta = soup.find("meta", {"name": "csrf-token"})
        if meta:
            form_data["authenticity_token"] = meta.get("content", "")

    # Fill in credentials — try common field-name patterns
    email_field = (
        form.find("input", {"name": re.compile(r"email", re.I)})
        or form.find("input", {"type": "email"})
    )
    password_field = (
        form.find("input", {"name": re.compile(r"password", re.I)})
        or form.find("input", {"type": "password"})
    )

    if email_field is None or password_field is None:
        log.error("Could not find email/password fields in login form")
        return False

    form_data[email_field["name"]] = email
    form_data[password_field["name"]] = password

    # Determine form action URL
    action = form.get("action", sign_in_url)
    if action.startswith("/"):
        action = SUGARWOD_BASE + action
    elif not action.startswith("http"):
        action = sign_in_url

    log.info("Submitting login form to %s", action)
    resp = session.post(action, data=form_data, allow_redirects=True, timeout=30)

    # Login failed if we're still on sign_in page or got a 4xx
    if resp.status_code >= 400 or "sign_in" in resp.url:
        log.error("Login failed — check SUGARWOD_EMAIL and SUGARWOD_PASSWORD")
        return False

    log.info("Logged in successfully (landed on %s)", resp.url)
    return True


# ──────────────────────────────────────────────────────────────
# Calendar fetching & parsing
# ──────────────────────────────────────────────────────────────

def fetch_calendar_week(session: requests.Session, monday: datetime) -> list[dict]:
    """Fetch and parse workouts for the week starting on *monday*."""
    week_str = monday.strftime("%Y%m%d")
    url = (
        f"{SUGARWOD_BASE}/workouts/calendar"
        f"?week={week_str}&track=workout-of-the-day"
    )
    log.info("Fetching calendar for week %s", week_str)
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return parse_calendar_html(resp.text, monday)


def parse_calendar_html(html: str, week_monday: datetime) -> list[dict]:
    """
    Parse the SugarWOD calendar HTML into a list of per-day workout dicts.

    SugarWOD renders the calendar as a Bootstrap-style grid where each day
    is a column.  We try several selector strategies in order of specificity.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Strategy 1: elements with an explicit data-date attribute
    day_elements = soup.find_all(attrs={"data-date": True})
    if day_elements:
        log.info("Strategy 1: found %d day elements via data-date", len(day_elements))
        workouts = []
        for el in day_elements[:7]:
            raw_date = el["data-date"]  # e.g. "2026-03-16" or "20260316"
            try:
                if "-" in raw_date:
                    date = datetime.strptime(raw_date, "%Y-%m-%d")
                else:
                    date = datetime.strptime(raw_date, "%Y%m%d")
            except ValueError:
                continue
            content = _extract_text(el)
            workouts.append(_build_workout(date, content))
        if workouts:
            return workouts

    # Strategy 2: table cells or divs that look like calendar day columns
    day_cols = (
        soup.select("td.day-column, div.day-column")
        or soup.select("[class*='day-col']")
        or soup.select("td[class*='day'], div[class*='day']")
    )
    if day_cols:
        log.info("Strategy 2: found %d day columns via CSS", len(day_cols))
        workouts = []
        for i, col in enumerate(day_cols[:7]):
            date = week_monday + timedelta(days=i)
            content = _extract_text(col)
            workouts.append(_build_workout(date, content))
        return workouts

    # Strategy 3: look for day headers like "MON 16" in text and slice
    log.info("Strategy 3: generic text-based day extraction")
    return _parse_by_day_headers(soup, week_monday)


def _extract_text(element) -> str:
    """Return clean multi-line text from a BS4 element."""
    lines = []
    for string in element.stripped_strings:
        lines.append(string)
    return "\n".join(lines)


def _build_workout(date: datetime, description: str) -> dict:
    return {
        "date": date.strftime("%Y-%m-%d"),
        "title": f"WOD {date.strftime('%A %d %B %Y')}",
        "description": description,
    }


def _parse_by_day_headers(soup: BeautifulSoup, week_monday: datetime) -> list[dict]:
    """
    Fallback: extract all page text and slice it by the MON/TUE/… day headers
    that SugarWOD renders in the calendar view.
    """
    full_text = soup.get_text(separator="\n")
    days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    workouts = []

    positions = []
    for i, abbr in enumerate(days):
        date = week_monday + timedelta(days=i)
        # Match "MON 16" or "MON\n16"
        pattern = rf"\b{abbr}\s+{date.day}\b"
        m = re.search(pattern, full_text)
        if m:
            positions.append((i, m.start(), m.end()))

    for idx, (day_i, start, end) in enumerate(positions):
        next_start = positions[idx + 1][1] if idx + 1 < len(positions) else len(full_text)
        content = full_text[end:next_start].strip()
        date = week_monday + timedelta(days=day_i)
        workouts.append(_build_workout(date, content))

    log.info("Strategy 3 extracted %d day(s)", len(workouts))
    return workouts


# ──────────────────────────────────────────────────────────────
# Gist storage
# ──────────────────────────────────────────────────────────────

def save_to_gist(gist_id: str, token: str, wod_data: dict) -> None:
    """Save WOD data as a file in an existing GitHub Gist."""
    payload = {
        "files": {
            GIST_FILENAME: {
                "content": json.dumps(wod_data, ensure_ascii=False, indent=2)
            }
        }
    }
    resp = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        json=payload,
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    log.info("WOD data saved to Gist %s as '%s'", gist_id, GIST_FILENAME)


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main() -> int:
    email = os.environ.get("SUGARWOD_EMAIL", "").strip()
    password = os.environ.get("SUGARWOD_PASSWORD", "").strip()
    gist_id = os.environ.get("GIST_ID", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()

    if not email or not password:
        log.error("SUGARWOD_EMAIL and SUGARWOD_PASSWORD environment variables are required")
        return 1

    session = requests.Session()
    session.headers.update(HEADERS)

    if not login(session, email, password):
        return 1

    now = datetime.now(AMS)
    this_monday = get_monday(now)
    next_monday = this_monday + timedelta(weeks=1)

    workouts: list[dict] = []
    for monday in [this_monday, next_monday]:
        try:
            week_workouts = fetch_calendar_week(session, monday)
            workouts.extend(week_workouts)
            log.info("Week %s: %d workout(s)", monday.strftime("%Y%m%d"), len(week_workouts))
        except Exception as exc:
            log.warning("Failed to fetch week %s: %s", monday.strftime("%Y%m%d"), exc)

    if not workouts:
        log.error("No workouts fetched")
        return 1

    wod_data = {
        "workouts": workouts,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    if gist_id and token:
        try:
            save_to_gist(gist_id, token, wod_data)
        except requests.HTTPError as exc:
            log.error("Failed to save WOD to Gist: %s", exc)
            return 1
    else:
        log.warning("GIST_ID or GITHUB_TOKEN not set — printing to stdout")
        print(json.dumps(wod_data, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
