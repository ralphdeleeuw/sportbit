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
# Athlete profile (used for AI coaching plans)
# ──────────────────────────────────────────────────────────────

ATHLETE_PROFILE = {
    "name": "Ralph de Leeuw",
    "weight_kg": 77,
    "experience": "intermediate-advanced (4+ jaar CrossFit)",
    "rx_preference": "mix van RX en Scaled — RX wanneer mogelijk",
    "injuries": "geen",
    "gym": "CrossFit Hilversum",
    "doel": "Uiteindelijk alles RX kunnen. Leeftijd 47, voelt zich goed en traint serieus.",
    "skill_focus": [
        "hardlooptempo (sneller worden op 400m/800m/1mi)",
        "back squat & front squat (techniek + kracht)",
        "double unders (consistentie en hoog volume)",
        "handstand push-ups (strikt en kipping, richting RX)",
        "pull-ups (kipping en butterfly, richting RX)",
        "handstand walk (afstand opbouwen)",
    ],
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

def login(session: requests.Session, email: str, password: str) -> tuple[str | None, str | None, str | None, str | None]:
    """
    Log in to SugarWOD and return (csrf, session_token, athlete_id, affiliate_id).

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
        return None, None, None, None

    session_token = None
    athlete_id = None
    affiliate_id = None
    try:
        body = resp.json()
        if isinstance(body, dict) and body.get("success") is False:
            log.error("Login rejected: %s", body.get("message", ""))
            return None, None, None, None
        log.info("Login JSON: %s", body)
        # Extract Parse Server session token and user IDs for direct API access
        if isinstance(body, dict):
            data = body.get("data") or body
            session_token = data.get("sessionToken") or body.get("sessionToken")
            if session_token:
                log.info("Got Parse sessionToken: %s…", session_token[:20])
            # Athlete and affiliate object IDs from the Parse pointers
            ath = data.get("athlete") or {}
            aff = data.get("affiliate") or {}
            athlete_id = (
                data.get("athleteId")
                or (ath.get("objectId") if isinstance(ath, dict) else None)
            )
            affiliate_id = (
                data.get("affiliateId")
                or data.get("affiliateName") and None  # affiliateName is a string, skip
                or (aff.get("objectId") if isinstance(aff, dict) else None)
            )
            if athlete_id:
                log.info("Got athlete objectId: %s", athlete_id)
            if affiliate_id:
                log.info("Got affiliate objectId: %s", affiliate_id)
    except ValueError:
        pass

    # Step 3: regenerate CSRF from the (now authenticated) _sw_session cookie
    new_csrf = _generate_csrf_from_session(session)
    if new_csrf:
        log.info("CSRF token after login: %s", new_csrf[:20] + "…")
        return new_csrf, session_token, athlete_id, affiliate_id

    log.warning("Could not generate CSRF token after login")
    return csrf, session_token, athlete_id, affiliate_id


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

def _extract_barbell_from_page(page) -> dict:
    """Extract the Current Barbell Maxes table from the athlete barbell page."""
    try:
        page.wait_for_selector("table", timeout=8000)
    except Exception:
        log.warning("[browser] No table found on barbell page")
        return {}
    try:
        result = page.evaluate("""
        () => {
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const headers = [...table.querySelectorAll('th')].map(th => th.textContent.trim());
                const hasBarbell = headers.some(h => /barbell/i.test(h) || /lift/i.test(h));
                const hasRM = headers.some(h => /\\dRM/.test(h));
                if (!hasBarbell && !hasRM) continue;
                const rmHeaders = headers.slice(1).filter(h => /\\dRM/.test(h));
                const rows = [...table.querySelectorAll('tbody tr')];
                const lifts = {};
                for (const row of rows) {
                    const cells = [...row.querySelectorAll('td')];
                    if (cells.length < 2) continue;
                    const liftName = cells[0].textContent.trim();
                    if (!liftName) continue;
                    const values = {};
                    for (let i = 0; i < rmHeaders.length; i++) {
                        const valText = (cells[i + 1] || {textContent: ''}).textContent.trim();
                        const num = parseFloat(valText);
                        if (!isNaN(num) && num > 0) values[rmHeaders[i]] = num;
                    }
                    if (Object.keys(values).length > 0) lifts[liftName] = values;
                }
                if (Object.keys(lifts).length > 0) return lifts;
            }
            return {};
        }
        """)
        return result or {}
    except Exception as exc:
        log.warning("[browser] Failed to extract barbell table: %s", exc)
        return {}


def _extract_prs_from_page(page) -> list[dict]:
    """Extract the Personal Records table from the athlete PRs page."""
    try:
        page.wait_for_selector("table", timeout=8000)
    except Exception:
        log.warning("[browser] No table found on PRs page")
        return []
    try:
        result = page.evaluate("""
        () => {
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const headers = [...table.querySelectorAll('th')].map(th => th.textContent.trim());
                const hasPR = headers.some(h => /pr|workout|personal/i.test(h));
                if (!hasPR) continue;
                const rows = [...table.querySelectorAll('tbody tr')];
                return rows.map(row => {
                    const cells = [...row.querySelectorAll('td')];
                    return {
                        workout: (cells[0] || {textContent: ''}).textContent.trim(),
                        date:    (cells[1] || {textContent: ''}).textContent.trim(),
                        notes:   (cells[2] || {textContent: ''}).textContent.trim(),
                    };
                }).filter(r => r.workout);
            }
            return [];
        }
        """)
        return result or []
    except Exception as exc:
        log.warning("[browser] Failed to extract PRs table: %s", exc)
        return []


def fetch_all_workouts_playwright(
    email: str,
    password: str,
    weeks: list[datetime],
) -> dict | None:
    """
    Use a headless Chromium browser to log in via the real HTML form and then
    intercept the XHR calls the SPA makes to load workout data.  Also scrapes
    barbell lifts and personal records from the athlete profile pages.

    Returns a dict with keys "workouts", "barbell_lifts", "personal_records",
    or None if the overall fetch failed.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        log.warning("playwright not installed; skipping browser approach")
        return None

    log.info("Starting Playwright headless browser")
    captured: list[dict] = []

    def _on_response(response) -> None:
        try:
            ct = response.headers.get("content-type", "")
            if response.status != 200 or "json" not in ct:
                return
            url = response.url
            # Skip third-party analytics calls
            if "sugarwod.com" not in url:
                return
            data = response.json()
            log.info("  [browser] %s → %s", url, str(data)[:200])
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

            # ── 1. Log in via the real HTML form ─────────────────────────
            # The browser handles CSRF tokens and cookies automatically.
            log.info("[browser] Navigating to login page")
            page.goto(f"{SUGARWOD_BASE}/login", wait_until="domcontentloaded",
                      timeout=30000)

            log.info("[browser] Filling login form")
            # Use type() (character-by-character) instead of fill() to ensure
            # React's synthetic onChange events fire on every keystroke.
            email_input = page.locator('input[type="email"], input[name="email"]').first
            email_input.click()
            email_input.type(email)

            password_input = page.locator('input[type="password"]').first
            password_input.click()
            password_input.type(password)

            # Wait for React to re-enable the submit button (it starts disabled),
            # then click it. If it never enables, fall back to pressing Enter.
            try:
                page.locator('#login-button').wait_for(state="enabled", timeout=5000)
                page.locator('#login-button').click()
                log.info("[browser] Clicked enabled submit button")
            except Exception:
                log.info("[browser] Submit button still disabled; pressing Enter")
                password_input.press("Enter")

            # Wait for the SPA to redirect away from the login page
            try:
                page.wait_for_function(
                    "!window.location.href.includes('/login')",
                    timeout=15000,
                )
                log.info("[browser] Login successful, now at: %s", page.url)
            except Exception as exc:
                log.warning("[browser] Login did not redirect: %s — %s", page.url, exc)
                # Check if we're still on login page (auth failed)
                if "/login" in page.url:
                    log.warning("[browser] Aborting — still on login page")
                    browser.close()
                    return None

            # ── 2. Load the workouts page once to get CSRF token + trackId ───
            # The SPA ignores the ?week= URL param and always loads the current
            # week. Instead of fighting the router, we load once to grab the
            # browser credentials (CSRF token, trackId, session cookies), then
            # call /api/workouts directly for each requested week.
            first_week_str = weeks[0].strftime("%Y%m%d")
            captured.clear()
            log.info("[browser] Loading workouts page to capture credentials")
            page.goto(
                f"{SUGARWOD_BASE}/workouts?week={first_week_str}&track=workout-of-the-day",
                wait_until="networkidle",
                timeout=30000,
            )
            log.info("[browser] Captured %d JSON responses", len(captured))

            # Extract CSRF token and trackId from the intercepted /api/workouts URL
            from urllib.parse import urlparse, parse_qs
            api_csrf: str | None = None
            track_id: str | None = None
            for item in captured:
                if "/api/workouts" in item["url"] and "week=" in item["url"]:
                    p = parse_qs(urlparse(item["url"]).query)
                    api_csrf = p.get("_csrf", [None])[0]
                    track_id = p.get("trackId", [None])[0]
                    log.info("[browser] Extracted _csrf=%s… trackId=%s",
                             api_csrf[:10] if api_csrf else "none", track_id)
                    break

            if not api_csrf or not track_id:
                log.warning("[browser] Could not extract CSRF/trackId from browser")
                browser.close()
                return None

            # Capture session cookies from the browser context
            browser_cookies = {
                c["name"]: c["value"] for c in context.cookies()
                if "sugarwod.com" in c.get("domain", "")
            }
            log.info("[browser] Captured %d session cookies", len(browser_cookies))

            # ── 3. Scrape barbell lifts ───────────────────────────────────────
            barbell_lifts: dict = {}
            log.info("[browser] Navigating to barbell lifts page")
            captured.clear()
            try:
                page.goto(
                    f"{SUGARWOD_BASE}/athletes/me#barbell",
                    wait_until="networkidle",
                    timeout=30000,
                )
                # First check if any intercepted XHR contained barbell data
                for item in captured:
                    url_lower = item["url"].lower()
                    if any(k in url_lower for k in ("barbell", "lift_max", "liftmax")):
                        log.info("[browser] Barbell data found in XHR: %s", item["url"])
                        data = item["data"]
                        if isinstance(data, dict):
                            results = data.get("data") or data.get("results") or []
                            for r in results:
                                name = r.get("name") or r.get("title") or ""
                                if name:
                                    barbell_lifts[name] = {
                                        k: r[k] for k in ("1RM", "2RM", "3RM", "5RM")
                                        if r.get(k)
                                    }
                        break
                # Fall back to DOM parsing if XHR didn't yield data
                if not barbell_lifts:
                    barbell_lifts = _extract_barbell_from_page(page)
                log.info("[browser] Extracted %d barbell lifts", len(barbell_lifts))
            except Exception as exc:
                log.warning("[browser] Barbell lifts fetch failed: %s", exc)

            # ── 4. Scrape personal records ────────────────────────────────────
            personal_records: list[dict] = []
            log.info("[browser] Navigating to personal records page")
            captured.clear()
            try:
                from_date = (datetime.now(AMS) - timedelta(days=180)).strftime("%Y%m%d")
                to_date = datetime.now(AMS).strftime("%Y%m%d")
                page.goto(
                    f"{SUGARWOD_BASE}/athletes/me?date_from={from_date}&date_to={to_date}#prs",
                    wait_until="networkidle",
                    timeout=30000,
                )
                # Check XHR first
                for item in captured:
                    url_lower = item["url"].lower()
                    if any(k in url_lower for k in ("personal_record", "/prs", "/pr")):
                        log.info("[browser] PR data found in XHR: %s", item["url"])
                        data = item["data"]
                        if isinstance(data, (list, dict)):
                            results = data if isinstance(data, list) else (
                                data.get("data") or data.get("results") or []
                            )
                            for r in results:
                                personal_records.append({
                                    "workout": r.get("workout") or r.get("name") or r.get("title") or "",
                                    "date": str(r.get("date") or r.get("achieved_at") or ""),
                                    "notes": r.get("notes") or "",
                                })
                        break
                # Fall back to DOM parsing
                if not personal_records:
                    personal_records = _extract_prs_from_page(page)
                log.info("[browser] Extracted %d personal records", len(personal_records))
            except Exception as exc:
                log.warning("[browser] Personal records fetch failed: %s", exc)

            browser.close()

            # ── 3. Direct API calls for each week ────────────────────────────
            # Now that we have valid credentials, use requests for each week so
            # we control the ?week= parameter precisely.
            api_session = requests.Session()
            api_session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{SUGARWOD_BASE}/workouts",
            })
            requests.utils.add_dict_to_cookiejar(api_session.cookies, browser_cookies)

            for monday in weeks:
                week_str = monday.strftime("%Y%m%d")
                ts = str(int(time.time() * 1000))
                log.info("[browser→http] Fetching week %s via /api/workouts", week_str)
                try:
                    resp = api_session.get(
                        f"{SUGARWOD_BASE}/api/workouts",
                        params={
                            "week": week_str,
                            "track": "workout-of-the-day",
                            "trackId": track_id,
                            "_csrf": api_csrf,
                            "_": ts,
                        },
                        timeout=30,
                    )
                    log.info("  → HTTP %d | %s", resp.status_code, resp.text[:500])
                    if resp.status_code == 200:
                        data = resp.json()
                        results = data.get("data") or data.get("workouts") or []
                        if results:
                            log.info("  Got %d workouts for week %s",
                                     len(results), week_str)
                            # Log first item in full so we can see the exact field names
                            log.info("  First item keys/values: %s",
                                     json.dumps(results[0], default=str)[:1000])
                            all_workouts.extend(_parse_parse_workouts(results, week_str))
                        else:
                            log.info("  No workouts for week %s (not programmed yet?)",
                                     week_str)
                except Exception as exc:
                    log.warning("  Error fetching week %s: %s", week_str, exc)

    except Exception as exc:
        log.warning("Playwright error: %s", exc)
        return None

    if not all_workouts:
        return None
    return {
        "workouts": all_workouts,
        "barbell_lifts": barbell_lifts,
        "personal_records": personal_records,
    }


def fetch_workouts_week(
    session: requests.Session,
    monday: datetime,
    csrf: str | None,
    session_token: str | None = None,
    athlete_id: str | None = None,
    affiliate_id: str | None = None,
) -> list[dict]:
    """
    Fetch workouts for one week.

    Tries in order:
    1. SugarWOD custom /public/api/v1/ endpoints (affiliate/athlete-scoped)
    2. HTML calendar endpoint (fallback with structure-aware parsing)
    """
    week_str = monday.strftime("%Y%m%d")

    # ── 1. Custom JSON API endpoint ─────────────────────────────────────
    workouts = _fetch_via_json_api(
        session, monday, week_str, csrf, session_token,
        athlete_id=athlete_id, affiliate_id=affiliate_id,
    )
    if workouts is not None:
        return workouts

    # ── 2. HTML calendar (scraping fallback) ────────────────────────────
    return _fetch_via_html(session, monday, week_str, csrf)



def _fetch_via_json_api(
    session: requests.Session,
    monday: datetime,
    week_str: str,
    csrf: str | None,
    session_token: str | None,
    athlete_id: str | None = None,
    affiliate_id: str | None = None,
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
    json_headers = {
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": base_referer,
        "Origin": SUGARWOD_BASE,
    }

    # IMPORTANT: never manually set a "Cookie" header — doing so causes
    # requests to send a partial cookie alongside the session jar, which
    # triggers the server to clear _sw_ath/_sw_aff via Set-Cookie and
    # corrupts the session for all subsequent calls.

    # Build dynamic affiliate/athlete endpoints from login data
    _aff = affiliate_id or "oqCrVKvRUY"
    _ath = athlete_id or "8lDP7kJHFN"

    attempts = [
        # ── A. Affiliate-scoped workouts (most likely correct endpoint)
        ("affiliate workouts API",
         f"{SUGARWOD_BASE}/public/api/v1/affiliates/{_aff}/workouts", dict(
            params={"week": week_str, "track": "workout-of-the-day"},
            headers=json_headers,
        )),
        # ── B. Affiliate workouts with flat affiliateId param
        ("affiliate workouts flat param",
         f"{SUGARWOD_BASE}/public/api/v1/workouts", dict(
            params={"week": week_str, "track": "workout-of-the-day",
                    "affiliateId": _aff},
            headers=json_headers,
        )),
        # ── C. Athlete-scoped workouts endpoint
        ("athlete workouts API",
         f"{SUGARWOD_BASE}/public/api/v1/athletes/{_ath}/workouts", dict(
            params={"week": week_str},
            headers=json_headers,
        )),
        # ── D. XHR request to the workouts page (no _csrf needed for GET)
        ("workouts XHR no _csrf", WORKOUTS_URL, dict(
            params=base_params,
            headers=json_headers,
        )),
        # ── E. Whiteboard endpoint (athlete-facing view)
        ("whiteboard", f"{SUGARWOD_BASE}/whiteboard", dict(
            params=base_params,
            headers=json_headers,
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


_SKIP_TITLES = ("warm", "access")  # warming up + accessory (EN/NL)


def _parse_parse_workouts(results: list[dict], week_str: str | None = None) -> list[dict]:
    """Convert Parse Server workout objects to our standard format."""
    # Derive monday from week_str (YYYYMMDD) as fallback date source
    monday_fallback: datetime | None = None
    if week_str and len(week_str) == 8:
        try:
            monday_fallback = datetime.strptime(week_str, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    workouts = []
    for item in results:
        title_raw = item.get("title") or item.get("name") or "WOD"
        # Skip warming-up and accessory entries — they clutter the WOD display
        if any(kw in title_raw.lower() for kw in _SKIP_TITLES):
            continue

        # scheduledDateInteger is SugarWOD's primary date field (e.g. 20260322)
        date_int = item.get("scheduledDateInteger")
        date_str = ""
        if date_int:
            try:
                date_str = datetime.strptime(str(date_int), "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                pass

        if not date_str:
            # Fallback: try other known field names
            date_val = (
                item.get("scheduledDate")
                or item.get("date")
                or item.get("workoutDate")
                or item.get("scheduledAt")
            )
            if isinstance(date_val, dict):
                date_val = date_val.get("iso", "") or date_val.get("value", "")
            if date_val:
                try:
                    date_str = datetime.fromisoformat(
                        str(date_val).replace("Z", "+00:00")
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    pass

        if not date_str and monday_fallback:
            # Fallback: assign Monday of the requested week
            log.info("  No date for '%s' — assigning Monday %s",
                     title_raw, monday_fallback.strftime("%Y-%m-%d"))
            date_str = monday_fallback.strftime("%Y-%m-%d")

        description = (
            item.get("description")
            or item.get("content")
            or item.get("workout")
            or ""
        )
        workouts.append({"date": date_str, "title": title_raw, "description": description})
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
# AI workout plan generation
# ──────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()


def generate_workout_plans(
    upcoming_workouts: list[dict],
    barbell_lifts: dict,
    athlete_profile: dict,
) -> dict[str, str]:
    """
    Call the Claude API to generate a personalised execution plan for each
    upcoming workout.  Requires ANTHROPIC_API_KEY to be set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping workout plan generation")
        return {}

    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed — skipping workout plan generation")
        return {}

    client = anthropic.Anthropic(api_key=api_key)

    barbell_text = (
        "\n".join(
            f"- {lift}: " + ", ".join(f"{rm}: {val}kg" for rm, val in sorted(maxes.items()))
            for lift, maxes in sorted(barbell_lifts.items())
        )
        if barbell_lifts
        else "Niet beschikbaar"
    )

    plans: dict[str, str] = {}
    for workout in upcoming_workouts:
        date = workout.get("date", "")
        title = workout.get("title", "WOD")
        description = _strip_html(workout.get("description", ""))
        if not description:
            continue

        skill_focus_text = "\n".join(
            f"- {s}" for s in athlete_profile.get("skill_focus", [])
        )
        prompt = f"""Je bent een ervaren CrossFit coach. Genereer een beknopt, praktisch uitvoeringsplan.

Atleet: {athlete_profile['name']}
Lichaamsgewicht: {athlete_profile['weight_kg']} kg
Ervaring: {athlete_profile['experience']}
Doel: {athlete_profile.get('doel', '')}
RX/Scaled voorkeur: {athlete_profile['rx_preference']}
Blessures: {athlete_profile['injuries']}

Persoonlijke focusgebieden (bewegen waarbij groei gewenst is):
{skill_focus_text}

Barbell maxima (kg):
{barbell_text}

Workout ({date} — {title}):
{description}

Geef een plan met:
1. Aanbevolen gewichten voor barbell movements (met % van 1RM als referentie)
2. Pacing strategie en sets/reps verdeling
3. 1–2 concrete tips voor deze specifieke workout
4. **Skill-tip**: Als een of meer van de focusgebieden in deze workout voorkomen, geef dan één gerichte verbeteringstip specifiek gericht op het sneller bereiken van RX-niveau voor die beweging (techniek, drills, mindset). Sla deze sectie over als geen van de focusgebieden aanwezig is.

Wees direct en bondig. Maximaal 220 woorden. Geen inleiding."""

        try:
            log.info("Generating AI plan for %s (%s)", date, title)
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            plan_text = message.content[0].text.strip()
            plans[date] = plan_text
            log.info("Plan generated for %s (%d chars)", date, len(plan_text))
        except Exception as exc:
            log.warning("Failed to generate plan for %s: %s", date, exc)

    return plans


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
    # Include next week only from Sunday onwards — coaches typically publish
    # next week's programming on Sunday.
    weeks = [this_monday]
    if now.weekday() == 6:  # 6 = Sunday
        weeks.append(next_monday)
        log.info("Sunday: also fetching next week (%s)", next_monday.strftime("%Y%m%d"))

    # ── Primary: Playwright headless browser (handles login via real form) ─
    barbell_lifts: dict = {}
    personal_records: list[dict] = []

    playwright_result = fetch_all_workouts_playwright(email, password, weeks)
    if playwright_result is not None:
        workouts = playwright_result["workouts"]
        barbell_lifts = playwright_result.get("barbell_lifts", {})
        personal_records = playwright_result.get("personal_records", [])
        log.info(
            "Playwright fetched %d workouts, %d barbell lifts, %d PRs",
            len(workouts), len(barbell_lifts), len(personal_records),
        )
    else:
        # ── Fallback: direct HTTP requests (workouts only) ────────────────
        log.info("Falling back to HTTP request approach")
        csrf, session_token, athlete_id, affiliate_id = login(session, email, password)
        if csrf is None:
            log.warning("Proceeding without CSRF token — requests may be rejected")

        workouts = []
        for monday in weeks:
            try:
                week_workouts = fetch_workouts_week(
                    session, monday, csrf,
                    session_token=session_token,
                    athlete_id=athlete_id,
                    affiliate_id=affiliate_id,
                )
                workouts.extend(week_workouts)
                log.info("Week %s: %d workout(s)", monday.strftime("%Y%m%d"), len(week_workouts))
            except Exception as exc:
                log.warning("Failed to fetch week %s: %s", monday.strftime("%Y%m%d"), exc)

    if not workouts:
        log.error("No workouts fetched")
        return 1

    # Build a date-keyed index so the PWA can look up workouts by date
    # without iterating the full list.
    today = now.date()
    by_date: dict[str, list[dict]] = {}
    for w in workouts:
        d = w.get("date")
        if d:
            by_date.setdefault(d, []).append(
                {"title": w["title"], "description": w["description"]}
            )

    # Generate AI coaching plans for upcoming workouts
    upcoming_workouts = [w for w in workouts if w.get("date", "") >= today.isoformat()]
    workout_plans = generate_workout_plans(upcoming_workouts, barbell_lifts, ATHLETE_PROFILE)

    wod_data = {
        "workouts": workouts,
        "by_date": by_date,
        "barbell_lifts": barbell_lifts,
        "personal_records": personal_records,
        "workout_plans": workout_plans,
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
