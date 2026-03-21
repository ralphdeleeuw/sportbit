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

import base64
import hashlib
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

    # Step 1: Visit sign-in page to establish session / get CSRF cookie
    resp = session.get(f"{SUGARWOD_BASE}/athletes/sign_in", timeout=30)
    resp.raise_for_status()
    log.info("Sign-in page: HTTP %d, final URL: %s", resp.status_code, resp.url)
    log.info("Cookies after sign-in page: %s", {k: v[:20] + "…" if len(v) > 20 else v
                                                  for k, v in session.cookies.items()})

    csrf = _extract_csrf(session, resp)
    log.info("CSRF token before login: %s", csrf[:20] + "…" if csrf else "none")

    # Step 2: POST credentials with CSRF token.
    #
    # The login endpoint requires a valid CSRF token — without it the server
    # returns HTTP 200 {"success":false,"message":"Your session has expired..."}.
    # With CSRF the token passes validation; we then try multiple credential
    # field-name conventions until one is accepted by Passport.js.
    #
    # Extra browser headers (Origin, Referer) are required: some csurf
    # configurations reject requests that lack them even with a correct token.
    login_headers = {
        "Accept": "application/json",
        "Origin": SUGARWOD_BASE,
        "Referer": f"{SUGARWOD_BASE}/login",
        "X-Requested-With": "XMLHttpRequest",
    }

    attempts = [
        # description, kwargs (csrf added below)
        ("JSON email/password + X-CSRF-Token header",
         dict(json={"email": email, "password": password})),
        ("JSON username/password + X-CSRF-Token header",
         dict(json={"username": email, "password": password})),
        ("JSON nested athlete{email,password} + X-CSRF-Token header",
         dict(json={"athlete": {"email": email, "password": password}})),
        ("JSON email/password/_csrf in body",
         dict(json={"email": email, "password": password, "_csrf": csrf})),
        ("form email/password + X-CSRF-Token header",
         dict(data={"email": email, "password": password})),
        ("form username/password + X-CSRF-Token header",
         dict(data={"username": email, "password": password})),
        ("form athlete[]/password + X-CSRF-Token header",
         dict(data={"athlete[email]": email, "athlete[password]": password})),
    ]

    resp = None
    for desc, kwargs in attempts:
        hdrs = {**login_headers, "X-CSRF-Token": csrf} if csrf else login_headers
        log.info("Trying login: %s", desc)
        r = session.post(LOGIN_URL, headers=hdrs, timeout=30, **kwargs)
        log.info("  → HTTP %d | %s", r.status_code, r.text[:120])
        if r.status_code in (200, 201):
            try:
                body = r.json()
                if isinstance(body, dict) and body.get("success") is True:
                    resp = r
                    break  # real success
                # success:false ("session expired" / wrong creds) → try next
            except ValueError:
                resp = r
                break  # non-JSON 200, assume success
            resp = r
            continue

        # 401 "Missing Credentials" → wrong field names; try next
        # Any other non-401 → unexpected failure, stop
        if r.status_code != 401:
            resp = r
            break
        resp = r  # keep last for error reporting

    log.info("Login response: HTTP %d, Content-Type: %s",
             resp.status_code, resp.headers.get("Content-Type", ""))
    log.info("Cookies after login: %s", {k: v[:30] + "…" if len(v) > 30 else v
                                          for k, v in session.cookies.items()})

    if resp.status_code not in (200, 201):
        log.error("Login failed with HTTP %d", resp.status_code)
        return None, None

    session_token = None
    try:
        body = resp.json()
        if isinstance(body, dict) and body.get("success") is False:
            log.error("Login rejected: %s", body.get("message", ""))
            return None, None
        log.info("Login JSON: %s", body)
        # Extract Parse Server session token for direct API access
        if isinstance(body, dict):
            session_token = (
                body.get("sessionToken")
                or (body.get("data") or {}).get("sessionToken")
            )
            if session_token:
                log.info("Got Parse sessionToken: %s…", session_token[:20])
    except ValueError:
        pass

    # Step 3: regenerate CSRF from the (now authenticated) _sw_session cookie
    new_csrf = _generate_csrf_from_session(session)
    if new_csrf:
        log.info("CSRF token after login: %s", new_csrf[:20] + "…")
        return new_csrf, session_token

    log.warning("Could not generate CSRF token after login")
    return csrf, session_token  # fall back to pre-login token


def _generate_csrf_from_session(session: requests.Session) -> str | None:
    """
    SugarWOD uses the Express.js `csurf` middleware.  The CSRF secret is stored
    in the _sw_session cookie as base64-encoded JSON {"csrfSecret": "..."}.
    The token is generated client-side (by the SPA's JS) as:

        salt     = 8 random bytes → base64url (no padding)
        token    = salt + "-" + base64url(SHA1(salt + "-" + secret))

    We replicate this in Python so we can send a valid _csrf without a browser.
    """
    sw_session = session.cookies.get("_sw_session")
    if not sw_session:
        log.warning("No _sw_session cookie found")
        return None

    # URL-decode if needed, then base64-decode
    try:
        from urllib.parse import unquote
        raw = unquote(sw_session)
        # Strip signature part (cookie-session signs as "payload.sig")
        payload = raw.split(".")[0]
        padded = payload + "=" * (4 - len(payload) % 4)
        data = json.loads(base64.b64decode(padded))
        secret = data.get("csrfSecret") or data.get("csrf_secret")
    except Exception as exc:
        log.warning("Could not decode _sw_session cookie: %s", exc)
        log.debug("_sw_session raw value: %s", sw_session[:100])
        return None

    if not secret:
        log.warning("csrfSecret not found in _sw_session cookie. Keys: %s",
                    list(data.keys()) if isinstance(data, dict) else "?")
        return None

    # Generate csurf-compatible token
    salt = base64.urlsafe_b64encode(os.urandom(8)).decode().rstrip("=")
    digest = hashlib.sha1(f"{salt}-{secret}".encode("ascii")).digest()
    token = salt + "-" + base64.urlsafe_b64encode(digest).decode().rstrip("=")
    log.info("Generated CSRF token from _sw_session secret")
    return token


def _extract_csrf(session: requests.Session, resp: requests.Response) -> str | None:
    """Try all known CSRF token sources."""
    # 1. Generate from _sw_session cookie (primary method for SugarWOD)
    token = _generate_csrf_from_session(session)
    if token:
        return token

    # 2. Explicit CSRF cookie
    for name in ("_csrf", "csrfToken", "XSRF-TOKEN"):
        val = session.cookies.get(name)
        if val:
            return val

    # 3. JSON response body
    try:
        data = resp.json()
        if isinstance(data, dict):
            for key in ("csrf", "_csrf", "csrfToken", "token", "csrf_token"):
                if data.get(key):
                    return data[key]
    except ValueError:
        pass

    # 4. HTML <meta name="csrf-token">
    soup = BeautifulSoup(resp.text, "html.parser")
    meta = soup.find("meta", {"name": "csrf-token"})
    if meta and meta.get("content"):
        return meta["content"]

    return None


# ──────────────────────────────────────────────────────────────
# Workout fetching
# ──────────────────────────────────────────────────────────────

def fetch_all_workouts_playwright(
    email: str,
    password: str,
    weeks: list[datetime],
) -> list[dict] | None:
    """
    Use a headless Chromium browser to log in to SugarWOD and intercept the
    XHR calls the SPA makes to load workout data.

    This bypasses all routing/CSRF complexity because we actually run the
    JavaScript — the browser handles cookies, CSRF, and API calls automatically.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        log.warning("playwright not installed; skipping browser approach")
        return None

    log.info("Starting Playwright headless browser")
    captured: list[dict] = []      # (url, data) pairs from intercepted responses

    def _on_response(response) -> None:
        try:
            ct = response.headers.get("content-type", "")
            if response.status != 200 or "json" not in ct:
                return
            url = response.url
            data = response.json()
            log.info("  [browser] %s → %s", url, str(data)[:120])
            captured.append({"url": url, "data": data})
        except Exception:
            pass

    all_workouts: list[dict] = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            page.on("response", _on_response)

            # ── 1. Login via JavaScript fetch ────────────────────────────
            # We bypass the React form entirely and call the login API
            # directly from JavaScript.  This way:
            # - We run from the correct origin (same-site cookies)
            # - We can read _sw_session from document.cookie
            # - We generate the csurf token using Web Crypto (SHA-1 HMAC)
            # - Auth cookies (_sw_ath, _sw_aff) are set in the browser ctx
            log.info("[browser] Navigating to login page")
            page.goto(f"{SUGARWOD_BASE}/login", wait_until="domcontentloaded",
                      timeout=30000)

            JS_LOGIN = r"""
async function swLogin(email, password) {
    // Parse _sw_session to get csrfSecret
    const cookies = {};
    document.cookie.split(';').forEach(c => {
        const idx = c.indexOf('=');
        if (idx > 0) cookies[c.slice(0, idx).trim()] = c.slice(idx + 1).trim();
    });
    const raw = cookies['_sw_session'];
    if (!raw) return {error: 'no _sw_session cookie'};

    let secret;
    try {
        const decoded = JSON.parse(atob(raw.split('.')[0]));
        secret = decoded.csrfSecret;
    } catch(e) { return {error: 'decode: ' + e.message}; }

    // Generate csurf token: salt "-" base64url(SHA1(salt+"-"+secret))
    const saltBytes = crypto.getRandomValues(new Uint8Array(8));
    const salt = btoa(String.fromCharCode(...saltBytes))
        .replace(/\+/g,'-').replace(/\//g,'_').replace(/=/g,'');
    const enc = new TextEncoder();
    const hashBuf = await crypto.subtle.digest('SHA-1',
        enc.encode(salt + '-' + secret));
    const hash = btoa(String.fromCharCode(...new Uint8Array(hashBuf)))
        .replace(/\+/g,'-').replace(/\//g,'_').replace(/=/g,'');
    const csrf = salt + '-' + hash;

    const resp = await fetch('/public/api/v1/login', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-CSRF-Token': csrf,
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({username: email, password: password})
    });
    const body = await resp.json();
    return {status: resp.status, body: body};
}
swLogin(arguments[0], arguments[1])
"""
            login_result = page.evaluate(JS_LOGIN, email, password)
            log.info("[browser] Login result: %s", str(login_result)[:300])

            if not login_result or not (login_result.get("body") or {}).get("success"):
                log.warning("[browser] Login failed, aborting Playwright")
                browser.close()
                return None

            log.info("[browser] Login successful")

            # ── 2. Fetch each week ────────────────────────────────────────
            for monday in weeks:
                week_str = monday.strftime("%Y%m%d")
                captured.clear()
                url = (f"{SUGARWOD_BASE}/workouts"
                       f"?week={week_str}&track=workout-of-the-day")
                log.info("[browser] Navigating to %s", url)
                page.goto(url, wait_until="networkidle", timeout=30000)

                # Process captured JSON responses
                for item in captured:
                    data = item["data"]
                    results = (
                        (data.get("workouts") or data.get("results")
                         or data.get("data"))
                        if isinstance(data, dict)
                        else data if isinstance(data, list)
                        else None
                    )
                    if results and isinstance(results, list):
                        log.info("[browser] Got %d workouts from %s",
                                 len(results), item["url"])
                        all_workouts.extend(_parse_parse_workouts(results))
                        break

            browser.close()

    except Exception as exc:
        log.warning("Playwright error: %s", exc)
        return None

    return all_workouts if all_workouts else None


def fetch_workouts_week(
    session: requests.Session,
    monday: datetime,
    csrf: str | None,
    session_token: str | None = None,
) -> list[dict]:
    """
    Fetch workouts for one week.

    Tries in order:
    1. Parse Server REST API (using the sessionToken from login)
    2. SugarWOD custom workouts API with JSON Accept header
    3. HTML calendar endpoint (fallback with structure-aware parsing)
    """
    week_str = monday.strftime("%Y%m%d")

    # ── 1. Parse Server direct API ──────────────────────────────────────
    if session_token:
        workouts = _fetch_via_parse_api(session, monday, week_str, session_token)
        if workouts is not None:
            return workouts

    # ── 2. Custom JSON API endpoint ─────────────────────────────────────
    workouts = _fetch_via_json_api(session, monday, week_str, csrf, session_token)
    if workouts is not None:
        return workouts

    # ── 3. HTML calendar (scraping fallback) ────────────────────────────
    return _fetch_via_html(session, monday, week_str, csrf)


def _fetch_via_parse_api(
    session: requests.Session,
    monday: datetime,
    week_str: str,
    session_token: str,
) -> list[dict] | None:
    """
    Query the SugarWOD custom JSON workouts API.

    Known endpoint variants based on the /public/api/v1/login pattern.
    """
    week_start = monday.strftime("%Y-%m-%dT00:00:00.000Z")
    week_end = (monday + timedelta(days=6)).strftime("%Y-%m-%dT23:59:59.999Z")

    base_headers = {
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": SUGARWOD_BASE,
        "Referer": f"{SUGARWOD_BASE}/workouts",
        "X-Parse-Session-Token": session_token,
    }

    endpoints_to_try = [
        # Custom REST-style API paths (same base as login endpoint)
        (f"{SUGARWOD_BASE}/public/api/v1/workouts", {"week": week_str, "track": "workout-of-the-day"}),
        (f"{SUGARWOD_BASE}/public/api/v1/workouts", {"startDate": week_start, "endDate": week_end}),
        # Parse Server at alternate paths (send browser-like headers to bypass Cloudflare)
        (f"{SUGARWOD_BASE}/parse/classes/TBWorkout", {
            "where": json.dumps({
                "scheduledDate": {
                    "$gte": {"__type": "Date", "iso": week_start},
                    "$lte": {"__type": "Date", "iso": week_end},
                }
            }),
            "limit": 50,
            "order": "scheduledDate",
        }),
    ]

    for url, params in endpoints_to_try:
        log.info("Trying API: %s", url)
        try:
            resp = session.get(url, params=params, headers=base_headers, timeout=30)
            log.info("  → HTTP %d, Content-Type: %s | %s",
                     resp.status_code,
                     resp.headers.get("Content-Type", ""),
                     resp.text[:200])
            if resp.status_code == 200 and "json" in resp.headers.get("Content-Type", ""):
                data = resp.json()
                results = (
                    data.get("results")
                    or data.get("workouts")
                    or data.get("data")
                    or (data if isinstance(data, list) else None)
                )
                if results:
                    log.info("API returned %d workouts", len(results))
                    return _parse_parse_workouts(results)
                log.info("API returned 200 JSON but no workout list: %s", list(data.keys()) if isinstance(data, dict) else type(data))
        except Exception as exc:
            log.warning("API error: %s", exc)

    return None


def _fetch_via_json_api(
    session: requests.Session,
    monday: datetime,
    week_str: str,
    csrf: str | None,
    session_token: str | None,
) -> list[dict] | None:
    """
    Try several approaches to get workout JSON from the workouts endpoint.

    Key insight: GET /workouts returns 401 JSON when *not* authenticated, but
    200 HTML (the SPA shell) when authenticated via cookies. To get JSON we
    either need to avoid triggering the "serve SPA" code path, or find the
    correct sub-API URL.
    """
    ts = str(int(time.time() * 1000))
    base_params = {"week": week_str, "track": "workout-of-the-day", "_": ts}
    base_referer = f"{SUGARWOD_BASE}/workouts?week={week_str}&track=workout-of-the-day"

    # IMPORTANT: never manually set a "Cookie" header — doing so causes
    # requests to send a partial cookie alongside the session jar, which
    # triggers the server to clear _sw_ath/_sw_aff via Set-Cookie and
    # corrupts the session for all subsequent calls.
    attempts = [
        # ── A. XHR without _csrf in params (GET doesn't need CSRF)
        ("workouts XHR no _csrf", WORKOUTS_URL, dict(
            params=base_params,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
                "Referer": base_referer,
            },
        )),
        # ── B. Affiliate-scoped workouts endpoint
        ("affiliate workouts API", f"{SUGARWOD_BASE}/public/api/v1/workouts", dict(
            params={"week": week_str, "track": "workout-of-the-day",
                    "affiliateId": "oqCrVKvRUY"},
            headers={"Accept": "application/json",
                     "X-Requested-With": "XMLHttpRequest",
                     "Referer": base_referer},
        )),
        # ── C. Athlete-scoped workouts endpoint
        ("athlete workouts API",
         f"{SUGARWOD_BASE}/public/api/v1/athletes/8lDP7kJHFN/workouts", dict(
            params={"week": week_str},
            headers={"Accept": "application/json",
                     "X-Requested-With": "XMLHttpRequest"},
        )),
        # ── D. Whiteboard endpoint (athlete-facing view)
        ("whiteboard", f"{SUGARWOD_BASE}/whiteboard", dict(
            params=base_params,
            headers={"X-Requested-With": "XMLHttpRequest",
                     "Accept": "application/json"},
        )),
        # ── E. workouts with _csrf (original approach)
        ("workouts XHR with _csrf", WORKOUTS_URL, dict(
            params={**base_params, "_csrf": csrf} if csrf else base_params,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
                "X-CSRF-Token": csrf or "",
                "Referer": base_referer,
            },
        )),
    ]

    for desc, url, kwargs in attempts:
        log.info("Trying: %s", desc)
        try:
            resp = session.get(url, timeout=30, **kwargs)
        except Exception as exc:
            log.warning("  Error: %s", exc)
            continue

        ct = resp.headers.get("Content-Type", "")
        set_cookie = resp.headers.get("Set-Cookie", "")
        log.info("  → HTTP %d, Content-Type: %s | %s",
                 resp.status_code, ct, resp.text[:200])
        if set_cookie:
            log.info("  Set-Cookie: %s", set_cookie[:200])

        if resp.status_code == 200 and "json" in ct:
            data = resp.json()
            results = (
                data.get("results") or data.get("workouts")
                or data.get("data")
                or (data if isinstance(data, list) else None)
            )
            if results:
                log.info("  Got %d workouts from '%s'", len(results), desc)
                return _parse_workouts_json({"workouts": results}, monday)
            # 200 JSON but empty / unexpected shape
            log.info("  200 JSON keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))

    return None


def _fetch_via_html(
    session: requests.Session,
    monday: datetime,
    week_str: str,
    csrf: str | None,
) -> list[dict]:
    """Fetch the HTML calendar page and scrape workout content."""
    params: dict = {
        "week": week_str,
        "track": "workout-of-the-day",
        "_": str(int(time.time() * 1000)),
    }
    if csrf:
        params["_csrf"] = csrf

    headers = {
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Referer": f"{SUGARWOD_BASE}/workouts",
    }

    log.info("Fetching workouts (HTML) for week %s", week_str)
    resp = session.get(WORKOUTS_URL, params=params, headers=headers, timeout=30)
    log.info("  → HTTP %d, Content-Type: %s",
             resp.status_code, resp.headers.get("Content-Type", ""))
    csp = resp.headers.get("Content-Security-Policy", "")
    if csp:
        # connect-src tells us which API origins the SPA calls
        import re as _re2
        m = _re2.search(r'connect-src([^;]+)', csp)
        if m:
            log.info("  CSP connect-src: %s", m.group(1).strip())
    resp.raise_for_status()

    # Log body text to aid debugging (skip <head> boilerplate)
    soup_debug = BeautifulSoup(resp.text, "html.parser")
    body = soup_debug.find("body")
    if body:
        body_text = body.get_text(separator="\n", strip=True)
        log.info("Body text (first 3000 chars):\n%s", body_text[:3000])
    else:
        log.info("HTML snippet (first 2000 chars):\n%s", resp.text[:2000])

    return _parse_workouts_html(resp.text, monday)


def _parse_parse_workouts(results: list[dict]) -> list[dict]:
    """Convert Parse Server workout objects to our standard format."""
    workouts = []
    for item in results:
        # Scheduled date can be a Parse Date object or ISO string
        date_val = item.get("scheduledDate") or item.get("date") or item.get("workoutDate")
        if isinstance(date_val, dict):
            date_val = date_val.get("iso", "")
        if date_val:
            try:
                date_str = datetime.fromisoformat(
                    date_val.replace("Z", "+00:00")
                ).strftime("%Y-%m-%d")
            except ValueError:
                date_str = date_val[:10]
        else:
            date_str = ""

        title = item.get("title") or item.get("name") or "WOD"
        description = (
            item.get("description")
            or item.get("content")
            or item.get("workout")
            or ""
        )
        workouts.append({"date": date_str, "title": title, "description": description})
    return workouts


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
    Parse a full Whiteboard Calendar HTML page or XHR fragment.
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── 1. JSON embedded in <script> tags ───────────────────────────────
    import re as _re
    for script in soup.find_all("script"):
        text = script.string or ""
        # Look for a JSON object/array that mentions workouts
        if not any(k in text for k in ("workout", "WOD", "scheduledDate", "TBWorkout")):
            continue
        # Try to extract JSON blobs
        for m in _re.finditer(r'(\{[^<]{20,}\}|\[[^<]{20,}\])', text):
            try:
                data = json.loads(m.group(0))
                results = (
                    (data.get("workouts") or data.get("results") or data.get("data"))
                    if isinstance(data, dict) else data if isinstance(data, list) else None
                )
                if results and isinstance(results, list) and len(results) > 0:
                    log.info("Found %d workouts in <script> JSON", len(results))
                    return _parse_parse_workouts(results)
            except (ValueError, AttributeError):
                pass

    workouts = []

    # ── 2. data-date elements ────────────────────────────────────────────
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

    now = datetime.now(AMS)
    this_monday = get_monday(now)
    next_monday = this_monday + timedelta(weeks=1)
    weeks = [this_monday, next_monday]

    # ── Primary: Playwright headless browser ──────────────────────────
    workouts = fetch_all_workouts_playwright(email, password, weeks)
    if workouts is not None:
        log.info("Playwright fetched %d workouts total", len(workouts))
    else:
        # ── Fallback: direct HTTP requests ────────────────────────────
        log.info("Falling back to HTTP request approach")
        csrf, session_token = login(session, email, password)
        if csrf is None:
            log.warning("Proceeding without CSRF token — requests may be rejected")

        workouts = []
        for monday in weeks:
            try:
                week_workouts = fetch_workouts_week(
                    session, monday, csrf, session_token=session_token
                )
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
