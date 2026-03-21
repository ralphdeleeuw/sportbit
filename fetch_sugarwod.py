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
    POST credentials to the SugarWOD REST login endpoint.
    Returns the CSRF token to use in subsequent XHR requests, or None on failure.

    SugarWOD uses a hybrid approach:
    - The /public/api/v1/login endpoint sets a session cookie AND returns a
      JSON body that may contain a CSRF token.
    - Subsequent XHR requests need that CSRF token as a query parameter.
    """
    log.info("Logging in as %s", email)

    # Try JSON body first (modern API), fall back to form data
    for content_type, body in [
        ("application/json", json.dumps({"email": email, "password": password})),
        (None, {"email": email, "password": password}),
    ]:
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
            headers["Accept"] = "application/json"

        if content_type:
            resp = session.post(LOGIN_URL, data=body, headers=headers, timeout=30)
        else:
            resp = session.post(LOGIN_URL, data=body, timeout=30)

        log.info("Login response: HTTP %d, Content-Type: %s",
                 resp.status_code, resp.headers.get("Content-Type", ""))
        log.debug("Login response body (first 500 chars): %s", resp.text[:500])

        if resp.status_code not in (200, 201):
            log.warning("Login attempt returned %d, trying next method", resp.status_code)
            continue

        # Try to extract CSRF token from JSON response
        try:
            data = resp.json()
            log.info("Login JSON keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))
            csrf = (
                data.get("csrf")
                or data.get("_csrf")
                or data.get("csrfToken")
                or data.get("token")
                or data.get("csrf_token")
            )
            if csrf:
                log.info("Got CSRF token from login response")
                return csrf
        except ValueError:
            log.debug("Login response is not JSON")

        # CSRF token might be in a cookie
        csrf_cookie = session.cookies.get("_csrf") or session.cookies.get("csrfToken")
        if csrf_cookie:
            log.info("Got CSRF token from cookie")
            return csrf_cookie

        # No CSRF token yet — fetch the main page to get it
        log.info("CSRF not in login response, fetching from app page")
        csrf = _get_csrf_from_page(session)
        if csrf:
            return csrf

        log.warning("Could not obtain CSRF token after login")
        return None

    log.error("All login attempts failed")
    return None


def _get_csrf_from_page(session: requests.Session) -> str | None:
    """
    Fetch a page that requires authentication and extract the CSRF token
    from the HTML meta tag or a dedicated session endpoint.
    """
    # Try the session/CSRF endpoint the web app uses
    for url in [
        f"{SUGARWOD_BASE}/session",
        f"{SUGARWOD_BASE}/workouts",
    ]:
        try:
            resp = session.get(url, timeout=30)
            # Try JSON first
            try:
                data = resp.json()
                csrf = (
                    data.get("csrf")
                    or data.get("_csrf")
                    or data.get("csrfToken")
                )
                if csrf:
                    log.info("Got CSRF from %s (JSON)", url)
                    return csrf
            except ValueError:
                pass

            # Try HTML meta tag
            soup = BeautifulSoup(resp.text, "html.parser")
            meta = soup.find("meta", {"name": "csrf-token"})
            if meta and meta.get("content"):
                log.info("Got CSRF from %s (HTML meta)", url)
                return meta["content"]

            # Try cookie after page load
            csrf_cookie = session.cookies.get("_csrf") or session.cookies.get("csrfToken")
            if csrf_cookie:
                log.info("Got CSRF from cookie after loading %s", url)
                return csrf_cookie

        except Exception as exc:
            log.debug("Could not get CSRF from %s: %s", url, exc)

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
