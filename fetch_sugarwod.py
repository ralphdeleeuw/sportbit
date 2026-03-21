#!/usr/bin/env python3
"""
SugarWOD WOD Fetcher for CrossFit Hilversum

Authenticates against SugarWOD's internal REST API, fetches the workout
calendar (the same XHR endpoint the web app uses), and stores the data in a
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
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

SUGARWOD_BASE = "https://app.sugarwod.com"
LOGIN_URL = f"{SUGARWOD_BASE}/public/api/v1/login"
WORKOUTS_URL = f"{SUGARWOD_BASE}/workouts"
GIST_FILENAME = "sugarwod_wod.json"
AMS = ZoneInfo("Europe/Amsterdam")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
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
    d = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())


# ──────────────────────────────────────────────────────────────
# Authentication
# ──────────────────────────────────────────────────────────────

def login(session: requests.Session, email: str, password: str) -> str | None:
    """
    Log in to SugarWOD and return the CSRF token for XHR requests.

    SugarWOD uses "double-submit cookie" CSRF protection:
    1. A GET to any page sets the _csrf cookie.
    2. That value must be included as the _csrf query/body param when POSTing.
    3. After login the same cookie value is used in all subsequent XHR requests.
    """
    log.info("Logging in as %s", email)

    # Step 1: Visit sign-in page to get the _csrf cookie
    resp = session.get(f"{SUGARWOD_BASE}/athletes/sign_in", timeout=30)
    resp.raise_for_status()

    csrf = _extract_csrf(session, resp)
    log.info("CSRF token before login: %s", csrf[:12] + "…" if csrf else "none")

    if not csrf:
        log.error("Could not obtain CSRF token from sign-in page")
        return None

    # Step 2: POST credentials + CSRF token to the login API
    resp = session.post(
        LOGIN_URL,
        data={"email": email, "password": password, "_csrf": csrf},
        timeout=30,
    )
    log.info("Login response: HTTP %d", resp.status_code)

    try:
        body = resp.json()
        log.info("Login JSON: %s", body)
    except ValueError:
        log.info("Login response (not JSON): %s", resp.text[:200])

    if resp.status_code not in (200, 201):
        log.error("Login failed with HTTP %d", resp.status_code)
        return None

    # Step 3: CSRF cookie may have rotated after login
    new_csrf = _extract_csrf(session, resp)
    final_csrf = new_csrf or csrf
    log.info("CSRF token after login: %s", final_csrf[:12] + "…" if final_csrf else "none")
    return final_csrf


def _extract_csrf(session: requests.Session, resp: requests.Response) -> str | None:
    """Extract CSRF token from cookies, JSON body, or HTML meta tag."""
    # Cookie (double-submit pattern — most common in SugarWOD)
    for name in ("_csrf", "csrfToken", "XSRF-TOKEN"):
        val = session.cookies.get(name)
        if val:
            return val

    # JSON response body
    try:
        data = resp.json()
        if isinstance(data, dict):
            for key in ("csrf", "_csrf", "csrfToken", "token", "csrf_token"):
                if data.get(key):
                    return data[key]
    except ValueError:
        pass

    # HTML <meta name="csrf-token">
    soup = BeautifulSoup(resp.text, "html.parser")
    meta = soup.find("meta", {"name": "csrf-token"})
    if meta and meta.get("content"):
        return meta["content"]

    return None


# ──────────────────────────────────────────────────────────────
# Workout fetching
# ──────────────────────────────────────────────────────────────

def fetch_workouts_week(
    session: requests.Session,
    monday: datetime,
    csrf: str | None,
) -> list[dict]:
    """
    Call the same XHR endpoint the SugarWOD web app uses to load the calendar.
    Returns a list of workout dicts (one per day).
    """
    week_str = monday.strftime("%Y%m%d")
    params: dict = {
        "week": week_str,
        "track": "workout-of-the-day",
        "_": str(int(time.time() * 1000)),
    }
    if csrf:
        params["_csrf"] = csrf

    xhr_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/html, */*",
        "Referer": (
            f"{SUGARWOD_BASE}/workouts/calendar"
            f"?week={week_str}&track=workout-of-the-day"
        ),
    }

    log.info("Fetching workouts for week %s", week_str)
    resp = session.get(WORKOUTS_URL, params=params, headers=xhr_headers, timeout=30)
    log.info("Workouts response: HTTP %d, Content-Type: %s",
             resp.status_code, resp.headers.get("Content-Type", ""))

    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")

    # JSON response
    if "json" in content_type:
        return _parse_workouts_json(resp.json(), monday)

    # HTML fragment response
    return _parse_workouts_html(resp.text, monday)


def _parse_workouts_json(data, monday: datetime) -> list[dict]:
    """Parse JSON workout response."""
    log.debug("JSON response keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))

    workouts = []

    # Common SugarWOD JSON shapes
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = (
            data.get("workouts")
            or data.get("data")
            or data.get("days")
            or data.get("results")
            or []
        )
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue

        date_str = (
            item.get("date")
            or item.get("scheduled_date")
            or item.get("workout_date")
        )
        title = item.get("title") or item.get("name") or "WOD"
        description = (
            item.get("description")
            or item.get("content")
            or item.get("workout")
            or ""
        )

        workouts.append({
            "date": date_str,
            "title": title,
            "description": description,
        })

    log.info("Parsed %d workout(s) from JSON", len(workouts))
    return workouts


def _parse_workouts_html(html: str, monday: datetime) -> list[dict]:
    """
    Parse an HTML fragment returned by the workouts XHR endpoint.
    Falls back to the full-page text-slice approach.
    """
    soup = BeautifulSoup(html, "html.parser")
    workouts = []

    # Try data-date elements
    day_elements = soup.find_all(attrs={"data-date": True})
    if day_elements:
        for el in day_elements[:7]:
            raw = el["data-date"].replace("-", "")
            try:
                date = datetime.strptime(raw, "%Y%m%d")
            except ValueError:
                continue
            content = "\n".join(el.stripped_strings)
            workouts.append(_build_workout(date, content))
        if workouts:
            log.info("HTML: extracted %d days via data-date", len(workouts))
            return workouts

    # Slice by day-of-week header text (MON 16, TUE 17, …)
    import re
    full_text = soup.get_text(separator="\n")
    days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    positions = []
    for i, abbr in enumerate(days):
        date = monday + timedelta(days=i)
        m = re.search(rf"\b{abbr}\s+{date.day}\b", full_text)
        if m:
            positions.append((i, m.start(), m.end()))

    for idx, (day_i, start, end) in enumerate(positions):
        next_start = positions[idx + 1][1] if idx + 1 < len(positions) else len(full_text)
        content = full_text[end:next_start].strip()
        date = monday + timedelta(days=day_i)
        workouts.append(_build_workout(date, content))

    log.info("HTML: extracted %d days via text headers", len(workouts))
    return workouts


def _build_workout(date: datetime, description: str) -> dict:
    return {
        "date": date.strftime("%Y-%m-%d"),
        "title": f"WOD {date.strftime('%A %d %B %Y')}",
        "description": description,
    }


# ──────────────────────────────────────────────────────────────
# Gist storage
# ──────────────────────────────────────────────────────────────

def save_to_gist(gist_id: str, token: str, wod_data: dict) -> None:
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
        log.error("SUGARWOD_EMAIL and SUGARWOD_PASSWORD are required")
        return 1

    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    csrf = login(session, email, password)
    if csrf is None:
        log.warning("Proceeding without CSRF token — requests may be rejected")

    now = datetime.now(AMS)
    this_monday = get_monday(now)
    next_monday = this_monday + timedelta(weeks=1)

    workouts: list[dict] = []
    for monday in [this_monday, next_monday]:
        try:
            week_workouts = fetch_workouts_week(session, monday, csrf)
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
